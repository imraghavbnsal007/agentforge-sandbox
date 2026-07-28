"""Two-user isolation across the whole surface.

User A installs AgentForge and registers a repository. User B signs in
separately and must not be able to see it, reach it, act on it, or borrow
A's installation — through the API *or* through a worker job.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AuthMode, TaskStatus
from app.core.security import CSRF_HEADER
from app.models import (
    GitHubInstallation,
    GitHubInstallationRepository,
    Project,
    Task,
    User,
    UserGitHubInstallation,
)
from app.services.github_app_api import InstallationToken
from app.services.github_credentials import (
    GitHubCredentialResolver,
    RepoOperation,
    RepositoryAccessError,
)
from app.services.kv_store import InMemoryKVStore
from app.services.session_store import SessionStore

REPO_A_ID = 900
INSTALLATION_A_ID = 500


@pytest.fixture
def app_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_client_id", "cid")
    monkeypatch.setattr(settings, "github_app_client_secret", "secret")
    monkeypatch.setattr(settings, "github_app_commit_name", "agentforge[bot]")
    monkeypatch.setattr(settings, "github_app_commit_email", "bot@example.com")


class FakeTokenService:
    def __init__(self) -> None:
        self.calls: list = []

    async def get_installation_token(self, installation_id, repository_ids=None):
        from datetime import datetime, timedelta, timezone

        self.calls.append((installation_id, repository_ids))
        return InstallationToken(
            token="ghs_should_not_be_reachable",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            permissions={"contents": "write", "pull_requests": "write"},
        )

    async def invalidate(self, installation_id, repository_ids=None): ...


async def _user(session: AsyncSession, gid: int, login: str) -> User:
    user = User(github_user_id=gid, github_login=login)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _sign_in(client: AsyncClient, kv: InMemoryKVStore, user: User) -> None:
    data = await SessionStore(kv, ttl_seconds=3600).create(user.id, user.github_login)
    client.cookies.set(settings.session_cookie_name, data.session_id)
    client.headers[CSRF_HEADER] = data.csrf_token


@pytest.fixture
async def world(session: AsyncSession) -> dict:
    """User A with an installation, a granted repository, a project and a task.
    User B exists with nothing."""
    alice = await _user(session, 1001, "alice")
    bob = await _user(session, 1002, "bob")

    installation = GitHubInstallation(
        github_installation_id=INSTALLATION_A_ID,
        account_id=1,
        account_login="alice",
    )
    session.add(installation)
    await session.commit()
    await session.refresh(installation)
    session.add(
        UserGitHubInstallation(user_id=alice.id, installation_id=installation.id)
    )
    session.add(
        GitHubInstallationRepository(
            installation_id=installation.id,
            github_repository_id=REPO_A_ID,
            owner="alice",
            name="secret-project",
            full_name="alice/secret-project",
            default_branch="main",
            private=True,
        )
    )
    project = Project(
        user_id=alice.id,
        name="alice/secret-project",
        description="",
        repo_path="",
        repo_url="https://github.com/alice/secret-project.git",
        default_branch="main",
        github_owner="alice",
        github_repo="secret-project",
        github_installation_id=installation.id,
        github_repository_id=REPO_A_ID,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    task = Task(
        project_id=project.id,
        title="Alice's task",
        request="private",
        status=TaskStatus.ready_for_review,
    )
    session.add(task)
    await session.flush()

    # A completed run with changes, so the publish path reaches credential
    # resolution rather than failing earlier for want of anything to publish.
    from app.core.enums import ChangeType, RunStatus
    from app.models import AgentRun, FileChange

    session.add(
        AgentRun(
            task_id=task.id,
            mode="llm",
            status=RunStatus.completed,
            summary="Alice's change",
            file_changes=[
                FileChange(
                    path="a.py",
                    change_type=ChangeType.modify,
                    diff="--- a/a.py\n+++ b/a.py\n",
                    is_binary=False,
                )
            ],
            test_results=[],
        )
    )
    await session.commit()
    await session.refresh(task)

    return {
        "alice": alice,
        "bob": bob,
        "installation": installation,
        "project": project,
        "task": task,
    }


# -- User A sees their own things ------------------------------------------


async def test_owner_sees_their_repository_and_project(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["alice"])

    repositories = (await client.get("/api/v1/repositories")).json()
    assert [r["full_name"] for r in repositories["repositories"]] == [
        "alice/secret-project"
    ]
    projects = (await client.get("/api/v1/projects")).json()
    assert [p["name"] for p in projects] == ["alice/secret-project"]


# -- User B sees none of it -------------------------------------------------


async def test_other_user_sees_no_repositories(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    body = (await client.get("/api/v1/repositories")).json()
    assert body["repositories"] == []
    assert body["has_installations"] is False


async def test_other_user_sees_no_projects(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    assert (await client.get("/api/v1/projects")).json() == []


async def test_other_user_sees_no_tasks(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    assert (await client.get("/api/v1/tasks")).json() == []


async def test_other_user_sees_no_installations(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    body = (await client.get("/api/v1/github/installations")).json()
    assert body["installations"] == []


# -- User B cannot reach A's objects: 404, never 403 ------------------------


async def test_other_user_reading_the_project_gets_404(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    response = await client.get(f"/api/v1/projects/{world['project'].id}")
    assert response.status_code == 404
    assert "secret-project" not in response.text


async def test_other_user_reading_the_task_gets_404(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    response = await client.get(f"/api/v1/tasks/{world['task'].id}")
    assert response.status_code == 404


async def test_other_user_cannot_create_a_task_on_the_project(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    response = await client.post(
        "/api/v1/tasks",
        json={
            "project_id": world["project"].id,
            "title": "intrusion",
            "request": "x",
        },
    )
    assert response.status_code == 404


async def test_other_user_cannot_publish_the_task(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    assert (
        await client.post(f"/api/v1/tasks/{world['task'].id}/approve")
    ).status_code == 404


async def test_other_user_cannot_analyze_the_project(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    assert (
        await client.post(f"/api/v1/projects/{world['project'].id}/analyze")
    ).status_code == 404


async def test_other_user_cannot_register_the_granted_repository(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    """Bob knows the repository id but has no installation granting it."""
    await _sign_in(client, kv, world["bob"])
    response = await client.post(
        "/api/v1/repositories/register",
        json={"github_repository_id": REPO_A_ID},
    )
    assert response.status_code == 403
    assert "alice" not in response.text.lower()


async def test_other_user_cannot_sync_alices_installation(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    assert (
        await client.post(
            f"/api/v1/github/installations/{INSTALLATION_A_ID}/sync"
        )
    ).status_code == 404


async def test_not_found_is_indistinguishable_from_never_existed(
    client: AsyncClient, kv: InMemoryKVStore, world: dict, app_mode
):
    await _sign_in(client, kv, world["bob"])
    real = await client.get(f"/api/v1/projects/{world['project'].id}")
    imaginary = await client.get("/api/v1/projects/987654")

    assert real.status_code == imaginary.status_code == 404
    # The bodies differ only by the id the caller themselves supplied, which
    # leaks nothing. What matters is that neither reveals anything about the
    # object: no name, no owner, no existence signal.
    def shape(response, project_id: int) -> str:
        return response.text.replace(str(project_id), "<id>")

    assert shape(real, world["project"].id) == shape(imaginary, 987654)
    assert "secret-project" not in real.text
    assert "alice" not in real.text.lower()


# -- Worker-side rejection, independent of the API -------------------------


async def test_worker_credential_resolution_rejects_a_foreign_user(
    session: AsyncSession, world: dict, app_mode
):
    """Even bypassing the API entirely, credentials cannot be resolved for
    someone who does not own the project."""
    tokens = FakeTokenService()
    resolver = GitHubCredentialResolver(session, tokens)

    with pytest.raises(RepositoryAccessError):
        await resolver.resolve(
            world["project"].id,
            RepoOperation.clone,
            user_id=world["bob"].id,
        )
    # No token was ever minted.
    assert tokens.calls == []


async def test_worker_resolution_requires_the_owner_to_still_be_linked(
    session: AsyncSession, world: dict, app_mode
):
    """Installation liveness is not enough: if the owner's link to the
    installation is withdrawn, their projects must stop resolving."""
    tokens = FakeTokenService()
    resolver = GitHubCredentialResolver(session, tokens)

    # Works while the link exists.
    assert await resolver.resolve(
        world["project"].id, RepoOperation.clone, user_id=world["alice"].id
    )

    await session.execute(
        UserGitHubInstallation.__table__.delete().where(
            UserGitHubInstallation.user_id == world["alice"].id
        )
    )
    await session.commit()

    with pytest.raises(RepositoryAccessError, match="no longer available"):
        await resolver.resolve(
            world["project"].id, RepoOperation.clone, user_id=world["alice"].id
        )


async def test_publish_worker_refuses_a_project_whose_owner_lost_access(
    session: AsyncSession, world: dict, app_mode
):
    """The publish job must revalidate rather than trust the queued task id."""
    from app.services.publisher import GitHubPublisher, PublishService

    task = world["task"]
    task.status = TaskStatus.publishing
    await session.commit()

    await session.execute(
        UserGitHubInstallation.__table__.delete().where(
            UserGitHubInstallation.user_id == world["alice"].id
        )
    )
    await session.commit()

    publisher = GitHubPublisher(
        resolver=GitHubCredentialResolver(session, FakeTokenService())
    )
    await PublishService(session, publisher=publisher).publish_task(task.id)

    await session.refresh(task)
    # Blocked, and returned to review with the work preserved.
    assert task.status == TaskStatus.ready_for_review


# -- Both users may hold the same repository name --------------------------


async def test_two_users_may_each_register_the_same_repository_name(
    session: AsyncSession, world: dict, app_mode
):
    """Per-owner uniqueness from migration 0011, seen end to end."""
    session.add(
        Project(
            user_id=world["bob"].id,
            name="alice/secret-project",
            description="",
            repo_path="",
        )
    )
    await session.commit()

    count = (
        await session.execute(
            select(func.count())
            .select_from(Project)
            .where(Project.name == "alice/secret-project")
        )
    ).scalar_one()
    assert count == 2
