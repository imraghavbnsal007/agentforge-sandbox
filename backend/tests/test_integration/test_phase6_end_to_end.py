"""End-to-end Phase 6 flow, steps A through Q.

One test walks the whole architecture: mocked GitHub sign-in, a verified App
installation, repository discovery, registration, task creation, a worker
run that clones with an installation token, review, approval, publishing to
a **real local bare repository**, a mocked pull request, and finally a signed
webhook that withdraws access and blocks the next attempt.

Nothing here touches GitHub. Every HTTP call is a scripted double; git runs
against a temporary bare repo; the agent output is deterministic.
"""

import hashlib
import hmac
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AuthMode, RunStatus, TaskStatus
from app.core.security import CSRF_HEADER
from app.models import (
    AgentRun,
    GitHubInstallation,
    GitHubInstallationRepository,
    Project,
    Task,
    User,
    UserGitHubInstallation,
)
from app.services.github_app_api import (
    InstallationInfo,
    InstallationToken,
    RepositoryInfo,
)
from app.services.github_credentials import (
    GitHubCredentialResolver,
    RepoOperation,
    RepositoryAccessError,
)
from app.services.kv_store import InMemoryKVStore
from app.services.oauth_github import GitHubProfile, OAuthStateStore

WEBHOOK_SECRET = "e2e-webhook-secret"
GITHUB_USER_ID = 4242
INSTALLATION_ID = 500
REPOSITORY_ID = 900
INSTALLATION_TOKEN = "ghs_e2e_installation_token"
OAUTH_TOKEN = "gho_e2e_user_token"


# ---------------------------------------------------------------- doubles --


class FakeOAuthClient:
    """Mocked GitHub sign-in (step A)."""

    async def exchange_code(self, code: str) -> str:
        return OAUTH_TOKEN

    async def fetch_profile(self, token: str) -> GitHubProfile:
        return GitHubProfile(
            github_user_id=GITHUB_USER_ID,
            github_login="octocat",
            avatar_url=None,
            display_name="The Octocat",
            email=None,
        )


def _installation_info(**kw) -> InstallationInfo:
    return InstallationInfo(
        github_installation_id=INSTALLATION_ID,
        account_id=1,
        account_login="octocat",
        account_type="User",
        target_type="User",
        repository_selection="selected",
        permissions={"contents": "write", "pull_requests": "write"},
        **kw,
    )


class FakeAppAPI:
    """Installation lookup + repository listing (steps B, C)."""

    repositories: list[RepositoryInfo] = []
    user_tokens_seen: list[str] = []

    async def list_user_installations(self, user_access_token: str):
        type(self).user_tokens_seen.append(user_access_token)
        return [_installation_info()]

    async def get_installation(self, app_jwt: str, github_installation_id: int):
        return _installation_info()

    async def list_installation_repositories(self, installation_token: str):
        return list(type(self).repositories)


class FakeTokenService:
    """Mints installation tokens (steps H, L). Records every request so
    per-operation resolution is provable."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, list[int] | None]] = []
        self.invalidated: list[int] = []
        self.counter = 0
        self._api = FakeAppAPI()

    async def get_installation_token(self, installation_id, repository_ids=None):
        self.calls.append((installation_id, repository_ids))
        self.counter += 1
        return InstallationToken(
            token=f"{INSTALLATION_TOKEN}_{self.counter}",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            permissions={"contents": "write", "pull_requests": "write"},
            repository_selection="selected",
        )

    async def invalidate(self, installation_id, repository_ids=None):
        self.invalidated.append(installation_id)


class RecordingPullRequestAPI:
    """Mocked PR creation (step N) — records, never calls GitHub."""

    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_pull_request(
        self, owner, repo, head, base, title, body, token=""
    ) -> str:
        self.created.append(
            {"owner": owner, "repo": repo, "head": head, "base": base,
             "token": token}
        )
        return f"https://github.com/{owner}/{repo}/pull/1"

    async def find_pull_request(self, owner, repo, head_branch, token):
        return None


# ------------------------------------------------------------- fixtures --


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """A real bare repository standing in for the GitHub remote (step M)."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(["git", "init", "--bare", "--initial-branch=main", "."], remote)

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(["git", "init", "--initial-branch=main", "."], seed)
    _git(["git", "config", "user.name", "Seed"], seed)
    _git(["git", "config", "user.email", "seed@example.com"], seed)
    (seed / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    _git(["git", "add", "-A"], seed)
    _git(["git", "commit", "-m", "initial"], seed)
    _git(["git", "remote", "add", "origin", str(remote)], seed)
    _git(["git", "push", "origin", "main"], seed)
    return remote


@pytest.fixture
def e2e_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_client_id", "cid")
    monkeypatch.setattr(settings, "github_app_client_secret", "csecret")
    monkeypatch.setattr(settings, "github_app_name", "agentforge-dev")
    monkeypatch.setattr(settings, "github_app_id", "123456")
    monkeypatch.setattr(settings, "github_app_private_key_path", "/tmp/k.pem")
    monkeypatch.setattr(settings, "github_app_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "github_app_commit_name", "agentforge[bot]")
    monkeypatch.setattr(
        settings, "github_app_commit_email", "bot@agentforge.example"
    )


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch, bare_remote: Path):
    FakeAppAPI.user_tokens_seen = []
    FakeAppAPI.repositories = [
        RepositoryInfo(
            github_repository_id=REPOSITORY_ID,
            owner="octocat",
            name="hello",
            full_name="octocat/hello",
            # The "clone URL" is the local bare repo.
            default_branch="main",
            private=True,
        )
    ]
    monkeypatch.setattr("app.api.routes.auth._oauth_client_factory", FakeOAuthClient)
    monkeypatch.setattr(
        "app.services.installation_service.GitHubAppAPI", FakeAppAPI
    )
    monkeypatch.setattr(
        "app.services.installation_service.generate_app_jwt", lambda: "jwt"
    )
    return FakeAppAPI


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()


# ------------------------------------------------------------------ test --


async def test_phase6_end_to_end(
    client: AsyncClient,
    session: AsyncSession,
    kv: InMemoryKVStore,
    bare_remote: Path,
    tmp_path: Path,
    e2e_settings,
    fake_github,
    caplog,
):
    caplog.set_level("INFO")

    # -- A. sign in through mocked GitHub OAuth, linking the installation --
    state = await OAuthStateStore(kv).issue("/", installation_id=INSTALLATION_ID)
    signin = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}"
        f"&installation_id={INSTALLATION_ID}&setup_action=install",
        follow_redirects=False,
    )
    assert signin.status_code == 303

    user = (
        await session.execute(
            select(User).where(User.github_user_id == GITHUB_USER_ID)
        )
    ).scalar_one()

    # Carry the session forward.
    from app.services.session_store import SessionStore

    data = await SessionStore(kv, ttl_seconds=3600).create(user.id, user.github_login)
    client.cookies.set(settings.session_cookie_name, data.session_id)
    client.headers[CSRF_HEADER] = data.csrf_token

    # -- B. the installation is linked and verified ------------------------
    installation = (
        await session.execute(
            select(GitHubInstallation).where(
                GitHubInstallation.github_installation_id == INSTALLATION_ID
            )
        )
    ).scalar_one()
    assert (
        await session.execute(
            select(func.count())
            .select_from(UserGitHubInstallation)
            .where(UserGitHubInstallation.user_id == user.id)
        )
    ).scalar_one() == 1
    # The OAuth token was used for verification and never stored.
    assert FakeAppAPI.user_tokens_seen == [OAUTH_TOKEN]

    # -- C/D. the installation exposes one repository, visible in discovery -
    session.add(
        GitHubInstallationRepository(
            installation_id=installation.id,
            github_repository_id=REPOSITORY_ID,
            owner="octocat",
            name="hello",
            full_name="octocat/hello",
            default_branch="main",
            private=True,
        )
    )
    await session.commit()

    listing = await client.get("/api/v1/repositories")
    assert listing.status_code == 200
    body = listing.json()
    assert [r["full_name"] for r in body["repositories"]] == ["octocat/hello"]
    assert body["repositories"][0]["is_registered"] is False

    # -- E. register it, by repository id (never a URL) --------------------
    registration = await client.post(
        "/api/v1/repositories/register",
        json={"github_repository_id": REPOSITORY_ID},
    )
    assert registration.status_code == 201
    project_id = registration.json()["id"]

    # Point the project at the local bare repo so git operations are real.
    project = await session.get(Project, project_id)
    project.repo_url = str(bare_remote)
    await session.commit()
    assert project.user_id == user.id
    assert project.github_installation_id == installation.id

    # -- F. create a task ---------------------------------------------------
    created = await client.post(
        "/api/v1/tasks",
        json={
            "project_id": project_id,
            "title": "Add multiply",
            "request": "Add a multiply function",
        },
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    # -- G/H. worker resolves credentials from the DB and clones -----------
    tokens = FakeTokenService()
    resolver = GitHubCredentialResolver(session, tokens)
    clone_credentials = await resolver.resolve(
        project_id, RepoOperation.clone, user_id=project.user_id
    )
    assert clone_credentials.mode == AuthMode.github_app
    assert clone_credentials.committer_name == "agentforge[bot]"
    # Scoped to exactly this repository.
    assert tokens.calls == [(INSTALLATION_ID, [REPOSITORY_ID])]

    from app.services.git_client import GitClient

    git = GitClient(
        token=clone_credentials.token,
        committer_name=clone_credentials.committer_name,
        committer_email=clone_credentials.committer_email,
    )
    workspace = tmp_path / "workspace"
    await git.clone(str(bare_remote), workspace, "main")
    assert (workspace / "calculator.py").exists()

    # -- I. deterministic agent change -------------------------------------
    target = workspace / "calculator.py"
    target.write_text(target.read_text() + "\n\ndef multiply(a, b):\n    return a * b\n")

    diff = subprocess.run(
        ["git", "diff"], cwd=workspace, capture_output=True, text=True
    ).stdout
    assert "multiply" in diff

    # -- J. the task reaches review ----------------------------------------
    from app.core.enums import ChangeType
    from app.models import FileChange

    run = AgentRun(
        task_id=task_id,
        mode="llm",
        status=RunStatus.completed,
        summary="Added multiply()",
        file_changes=[
            FileChange(
                path="calculator.py",
                change_type=ChangeType.modify,
                diff=diff,
                is_binary=False,
            )
        ],
        test_results=[],
    )
    session.add(run)
    task = await session.get(Task, task_id)
    task.status = TaskStatus.ready_for_review
    await session.commit()

    detail = await client.get(f"/api/v1/tasks/{task_id}")
    assert detail.json()["status"] == "ready_for_review"

    # -- K. approval moves it to publishing --------------------------------
    approval = await client.post(f"/api/v1/tasks/{task_id}/approve")
    assert approval.status_code == 200
    assert approval.json()["status"] == "publishing"

    # -- L/M/N. publish: fresh token, real push, mocked PR -----------------
    from app.services.publisher import GitHubPublisher, PublishService

    pr_api = RecordingPullRequestAPI()

    class NoTests:
        async def run_tests(self, workspace):
            from app.agent.executor import TestResultData

            return TestResultData(
                suite="pytest", passed=1, failed=0, errored=0, duration=0.0,
                output="ok", stderr="",
            )

    publisher = GitHubPublisher(
        api=pr_api, executor=NoTests(), resolver=resolver
    )
    calls_before_publish = len(tokens.calls)
    await PublishService(session, publisher=publisher).publish_task(task_id)

    published = await session.get(Task, task_id)
    await session.refresh(published)
    assert published.status == TaskStatus.completed

    # A fresh credential was resolved for clone, push and PR.
    assert len(tokens.calls) == calls_before_publish + 3
    # The branch really landed on the bare repository.
    branches = subprocess.run(
        ["git", "branch", "--list"], cwd=bare_remote, capture_output=True, text=True
    ).stdout
    assert "agentforge/task-" in branches
    # The PR was recorded, not sent.
    assert len(pr_api.created) == 1
    assert pr_api.created[0]["owner"] == "octocat"

    # The commit carries the App identity.
    author = subprocess.run(
        ["git", "log", "--all", "-1", "--pretty=%an <%ae>"],
        cwd=bare_remote, capture_output=True, text=True,
    ).stdout.strip()
    assert author == "agentforge[bot] <bot@agentforge.example>"

    # -- O. a signed webhook withdraws repository access -------------------
    payload = json.dumps(
        {
            "action": "removed",
            "installation": {
                "id": INSTALLATION_ID,
                "account": {"id": 1, "login": "octocat", "type": "User"},
            },
            "repositories_removed": [{"id": REPOSITORY_ID}],
        }
    ).encode()
    hook = await client.post(
        "/api/v1/github/webhooks",
        content=payload,
        headers={
            "X-GitHub-Event": "installation_repositories",
            "X-GitHub-Delivery": "e2e-1",
            "X-Hub-Signature-256": sign(payload),
            "Content-Type": "application/json",
        },
    )
    assert hook.status_code == 200

    # -- P. the next attempt is blocked ------------------------------------
    with pytest.raises(RepositoryAccessError, match="no longer available"):
        await resolver.resolve(
            project_id, RepoOperation.push, user_id=project.user_id
        )

    # It also disappears from discovery.
    after = await client.get("/api/v1/repositories")
    assert after.json()["repositories"] == []

    # -- Q. no token anywhere it must not be ------------------------------
    minted = [f"{INSTALLATION_TOKEN}_{i}" for i in range(1, tokens.counter + 1)]
    secrets = minted + [OAUTH_TOKEN]

    # ... not in the Redis substitute
    stored = kv.raw_values()
    for secret in secrets:
        assert secret not in stored

    # ... not in any API response
    for response in (listing, registration, created, detail, approval, after):
        for secret in secrets:
            assert secret not in response.text

    # ... not in git config or the remote URL
    config_text = (workspace / ".git" / "config").read_text()
    for secret in secrets:
        assert secret not in config_text
    assert "extraheader" not in config_text.lower()

    # ... not in the database
    all_rows = json.dumps(
        {
            "project": {k: str(v) for k, v in project.__dict__.items() if k[0] != "_"},
            "run": {k: str(v) for k, v in run.__dict__.items() if k[0] != "_"},
            "installation": {
                k: str(v) for k, v in installation.__dict__.items() if k[0] != "_"
            },
        }
    )
    for secret in secrets:
        assert secret not in all_rows

    # ... not in logs
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in secrets:
        assert secret not in logged
