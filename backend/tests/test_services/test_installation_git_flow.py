"""Git and PR operations on installation credentials.

Everything here runs against a real local bare repository and a mocked GitHub
API. No network call is made, and no live GitHub repository is touched.
"""

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.services.git_client import (
    DEFAULT_COMMITTER_EMAIL,
    GitAuthError,
    GitClient,
    is_auth_failure,
)
from app.services.github_api import GitHubAPI, GitHubAuthError
from app.services.github_app_api import InstallationToken
from app.services.github_app_token_service import GitHubAppTokenService
from app.services.kv_store import InMemoryKVStore

INSTALLATION_TOKEN = "ghs_installation_token_value"


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """A real bare repo with one commit on main, usable as an origin."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _run(["git", "init", "--bare", "--initial-branch=main", "."], remote)

    seed = tmp_path / "seed"
    seed.mkdir()
    _run(["git", "init", "--initial-branch=main", "."], seed)
    _run(["git", "config", "user.name", "Seed"], seed)
    _run(["git", "config", "user.email", "seed@example.com"], seed)
    (seed / "README.md").write_text("hello\n")
    _run(["git", "add", "-A"], seed)
    _run(["git", "commit", "-m", "initial"], seed)
    _run(["git", "remote", "add", "origin", str(remote)], seed)
    _run(["git", "push", "origin", "main"], seed)
    return remote


# -- clone / commit identity ------------------------------------------------


async def test_clone_records_the_supplied_commit_identity(
    bare_remote: Path, tmp_path: Path
):
    client = GitClient(
        token=INSTALLATION_TOKEN,
        committer_name="AgentForge[bot]",
        committer_email="bot@agentforge.example",
    )
    dest = tmp_path / "work"
    await client.clone(str(bare_remote), dest, "main")

    name = subprocess.run(
        ["git", "config", "user.name"], cwd=dest, capture_output=True, text=True
    ).stdout.strip()
    email = subprocess.run(
        ["git", "config", "user.email"], cwd=dest, capture_output=True, text=True
    ).stdout.strip()
    assert name == "AgentForge[bot]"
    assert email == "bot@agentforge.example"


async def test_clone_defaults_to_the_local_identity(
    bare_remote: Path, tmp_path: Path
):
    dest = tmp_path / "work"
    await GitClient().clone(str(bare_remote), dest, "main")
    email = subprocess.run(
        ["git", "config", "user.email"], cwd=dest, capture_output=True, text=True
    ).stdout.strip()
    assert email == DEFAULT_COMMITTER_EMAIL


# -- token never leaks ------------------------------------------------------


async def test_token_never_reaches_git_config(bare_remote: Path, tmp_path: Path):
    """The credential is passed per command, so nothing persists on disk."""
    client = GitClient(token=INSTALLATION_TOKEN)
    dest = tmp_path / "work"
    await client.clone(str(bare_remote), dest, "main")

    config_text = (dest / ".git" / "config").read_text()
    assert INSTALLATION_TOKEN not in config_text
    assert "extraheader" not in config_text.lower()


async def test_token_never_reaches_the_remote_url(
    bare_remote: Path, tmp_path: Path
):
    client = GitClient(token=INSTALLATION_TOKEN)
    dest = tmp_path / "work"
    await client.clone(str(bare_remote), dest, "main")

    remote_url = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=dest,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert INSTALLATION_TOKEN not in remote_url
    assert "x-access-token" not in remote_url


async def test_token_is_scrubbed_from_error_output(tmp_path: Path):
    client = GitClient(token=INSTALLATION_TOKEN)
    with pytest.raises(Exception) as excinfo:
        await client.clone(str(tmp_path / "missing.git"), tmp_path / "d", "main")
    assert INSTALLATION_TOKEN not in str(excinfo.value)


# -- push -------------------------------------------------------------------


async def test_push_lands_on_the_remote(bare_remote: Path, tmp_path: Path):
    client = GitClient(
        token=INSTALLATION_TOKEN,
        committer_name="AgentForge[bot]",
        committer_email="bot@agentforge.example",
    )
    dest = tmp_path / "work"
    await client.clone(str(bare_remote), dest, "main")
    await client.create_branch(dest, "agentforge/task-1")
    (dest / "added.txt").write_text("new\n")
    sha = await client.commit_all(dest, "Add a file")
    await client.push(dest, str(bare_remote), "agentforge/task-1")

    assert await client.remote_branch_sha(
        str(bare_remote), "agentforge/task-1"
    ) == sha


async def test_remote_branch_sha_is_none_when_absent(bare_remote: Path):
    client = GitClient()
    assert await client.remote_branch_sha(str(bare_remote), "never-pushed") is None


async def test_commit_is_attributed_to_the_configured_identity(
    bare_remote: Path, tmp_path: Path
):
    client = GitClient(
        token=INSTALLATION_TOKEN,
        committer_name="AgentForge[bot]",
        committer_email="bot@agentforge.example",
    )
    dest = tmp_path / "work"
    await client.clone(str(bare_remote), dest, "main")
    (dest / "x.txt").write_text("x\n")
    await client.commit_all(dest, "Change")

    author = subprocess.run(
        ["git", "log", "-1", "--pretty=%an <%ae>"],
        cwd=dest,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert author == "AgentForge[bot] <bot@agentforge.example>"


# -- auth failure detection -------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "fatal: Authentication failed for 'https://github.com/a/b'",
        "remote: Invalid username or password",
        "fatal: could not read Username for 'https://github.com'",
        "remote: Repository not found",
        "error: 403 Forbidden",
        "remote: Permission to a/b denied",
    ],
)
def test_credential_rejections_are_recognised(message: str):
    assert is_auth_failure(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "error: failed to push some refs",
        "fatal: couldn't find remote ref main",
        "error: patch does not apply",
    ],
)
def test_ordinary_git_failures_are_not_auth_failures(message: str):
    assert is_auth_failure(message) is False


async def test_auth_failure_raises_the_distinct_type(tmp_path: Path):
    """A credential rejection must be separable from an ordinary git error."""

    class RejectingClient(GitClient):
        async def _run(self, args, cwd=None, stdin=None):
            raise GitAuthError("git push failed: Authentication failed")

    with pytest.raises(GitAuthError):
        await RejectingClient(token="t").push(tmp_path, "https://x", "b")


# -- token refresh ----------------------------------------------------------


def _token(seconds: int, value: str = "ghs_fresh") -> InstallationToken:
    return InstallationToken(
        token=value,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=seconds),
        permissions={"contents": "write", "pull_requests": "write"},
    )


class ScriptedAPI:
    def __init__(self, tokens: list[InstallationToken]) -> None:
        self.tokens = tokens
        self.calls = 0

    async def create_installation_token(self, app_jwt, installation_id, repository_ids=None):
        token = self.tokens[min(self.calls, len(self.tokens) - 1)]
        self.calls += 1
        return token


async def test_token_near_expiry_is_reminted_before_the_next_operation(
    monkeypatch: pytest.MonkeyPatch,
):
    """A long task must not carry a nearly-expired token into its push."""
    monkeypatch.setattr(
        "app.services.github_app_token_service.generate_app_jwt", lambda: "jwt"
    )
    api = ScriptedAPI([_token(60, "ghs_stale"), _token(3600, "ghs_renewed")])
    service = GitHubAppTokenService(
        InMemoryKVStore(), api=api, refresh_margin_seconds=300
    )

    first = await service.get_installation_token(500, [900])
    second = await service.get_installation_token(500, [900])

    # The first token was inside the refresh margin, so it was never cached
    # and the second call minted afresh.
    assert first.token == "ghs_stale"
    assert second.token == "ghs_renewed"
    assert api.calls == 2


async def test_healthy_token_is_reused_across_operations(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.services.github_app_token_service.generate_app_jwt", lambda: "jwt"
    )
    api = ScriptedAPI([_token(3600, "ghs_good")])
    service = GitHubAppTokenService(
        InMemoryKVStore(), api=api, refresh_margin_seconds=300
    )

    await service.get_installation_token(500, [900])
    await service.get_installation_token(500, [900])
    assert api.calls == 1


# -- pull request creation --------------------------------------------------


def _api(handler) -> GitHubAPI:
    return GitHubAPI(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_pull_request_is_created_with_the_installation_token():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(
            201, json={"html_url": "https://github.com/o/r/pull/7"}
        )

    url = await _api(handler).create_pull_request(
        owner="o",
        repo="r",
        head="agentforge/task-1",
        base="main",
        title="T",
        body="B",
        token=INSTALLATION_TOKEN,
    )
    assert url == "https://github.com/o/r/pull/7"
    assert seen["auth"] == f"Bearer {INSTALLATION_TOKEN}"


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_rejected_credential_raises_the_auth_type(status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "no"})

    with pytest.raises(GitHubAuthError):
        await _api(handler).create_pull_request(
            owner="o", repo="r", head="h", base="main", title="T", body="B",
            token="t",
        )


async def test_pr_error_message_never_contains_the_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": f"bad {INSTALLATION_TOKEN}"})

    with pytest.raises(GitHubAuthError) as excinfo:
        await _api(handler).create_pull_request(
            owner="o", repo="r", head="h", base="main", title="T", body="B",
            token=INSTALLATION_TOKEN,
        )
    assert INSTALLATION_TOKEN not in str(excinfo.value)


async def test_find_pull_request_returns_an_existing_one():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "head=o%3Abranch" in str(request.url) or "head=o:branch" in str(
            request.url
        )
        return httpx.Response(
            200, json=[{"html_url": "https://github.com/o/r/pull/3"}]
        )

    found = await _api(handler).find_pull_request("o", "r", "branch", "t")
    assert found == "https://github.com/o/r/pull/3"


async def test_find_pull_request_returns_none_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    assert await _api(handler).find_pull_request("o", "r", "branch", "t") is None
