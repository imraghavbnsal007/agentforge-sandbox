"""Cross-user isolation at the HTTP boundary.

The rule under test everywhere here: another user's object is **404, never
403**, so a caller cannot use the response to learn that it exists.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AuthMode
from app.core.security import CSRF_HEADER
from app.models import AgentRun, Project, Task, User
from app.services.kv_store import InMemoryKVStore
from app.services.session_store import SessionStore


@pytest.fixture
def github_app_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_client_id", "cid")
    monkeypatch.setattr(settings, "github_app_client_secret", "secret")


async def _make_user(session: AsyncSession, github_id: int, login: str) -> User:
    user = User(github_user_id=github_id, github_login=login)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _make_project(
    session: AsyncSession, user: User, name: str = "acme/widget"
) -> Project:
    project = Project(
        user_id=user.id, name=name, description="", repo_path="sample_repo"
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def _make_task(session: AsyncSession, project: Project) -> Task:
    task = Task(project_id=project.id, title="T", request="R")
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def _sign_in(
    client: AsyncClient, kv: InMemoryKVStore, user: User
) -> AsyncClient:
    data = await SessionStore(kv, ttl_seconds=3600).create(user.id, user.github_login)
    client.cookies.set(settings.session_cookie_name, data.session_id)
    client.headers[CSRF_HEADER] = data.csrf_token
    return client


@pytest.fixture
async def two_users(session: AsyncSession) -> tuple[User, User]:
    alice = await _make_user(session, 1001, "alice")
    mallory = await _make_user(session, 1002, "mallory")
    return alice, mallory


# -- projects ---------------------------------------------------------------


async def test_project_list_shows_only_your_own(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode,
):
    alice, mallory = two_users
    await _make_project(session, alice, "alice/repo")
    await _make_project(session, mallory, "mallory/repo")

    await _sign_in(client, kv, alice)
    body = (await client.get("/api/v1/projects")).json()
    assert [p["name"] for p in body] == ["alice/repo"]


async def test_reading_another_users_project_is_404(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode,
):
    alice, mallory = two_users
    theirs = await _make_project(session, mallory)

    await _sign_in(client, kv, alice)
    assert (await client.get(f"/api/v1/projects/{theirs.id}")).status_code == 404


async def test_updating_another_users_project_is_404(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode,
):
    alice, mallory = two_users
    theirs = await _make_project(session, mallory)

    await _sign_in(client, kv, alice)
    response = await client.patch(
        f"/api/v1/projects/{theirs.id}/settings",
        json={
            "preferred_provider": None,
            "preferred_model": None,
            "preferred_execution_profile": None,
        },
    )
    assert response.status_code == 404


async def test_analyzing_another_users_project_is_404(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode,
):
    alice, mallory = two_users
    theirs = await _make_project(session, mallory)

    await _sign_in(client, kv, alice)
    assert (
        await client.post(f"/api/v1/projects/{theirs.id}/analyze")
    ).status_code == 404


# -- tasks ------------------------------------------------------------------


async def test_task_list_shows_only_your_own(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode,
):
    alice, mallory = two_users
    mine = await _make_project(session, alice, "alice/repo")
    theirs = await _make_project(session, mallory, "mallory/repo")
    await _make_task(session, mine)
    await _make_task(session, theirs)

    await _sign_in(client, kv, alice)
    body = (await client.get("/api/v1/tasks")).json()
    assert len(body) == 1
    assert body[0]["project_id"] == mine.id


async def test_reading_another_users_task_is_404(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode,
):
    alice, mallory = two_users
    theirs = await _make_task(session, await _make_project(session, mallory))

    await _sign_in(client, kv, alice)
    assert (await client.get(f"/api/v1/tasks/{theirs.id}")).status_code == 404


@pytest.mark.parametrize("action", ["retry", "approve", "reject"])
async def test_acting_on_another_users_task_is_404(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode, action: str,
):
    alice, mallory = two_users
    theirs = await _make_task(session, await _make_project(session, mallory))

    await _sign_in(client, kv, alice)
    response = await client.post(f"/api/v1/tasks/{theirs.id}/{action}")
    assert response.status_code == 404


async def test_creating_a_task_on_another_users_project_is_404(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode,
):
    alice, mallory = two_users
    theirs = await _make_project(session, mallory)

    await _sign_in(client, kv, alice)
    response = await client.post(
        "/api/v1/tasks",
        json={"project_id": theirs.id, "title": "T", "request": "R"},
    )
    assert response.status_code == 404


async def test_filtering_tasks_by_another_users_project_returns_nothing(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode,
):
    """A project_id filter must not become a way to read across tenants."""
    alice, mallory = two_users
    theirs = await _make_project(session, mallory)
    await _make_task(session, theirs)

    await _sign_in(client, kv, alice)
    body = (await client.get(f"/api/v1/tasks?project_id={theirs.id}")).json()
    assert body == []


# -- error shape ------------------------------------------------------------


async def test_not_found_response_does_not_confirm_existence(
    client: AsyncClient, kv: InMemoryKVStore, session: AsyncSession,
    two_users, github_app_mode,
):
    """The reply for someone else's project must be indistinguishable from
    the reply for one that never existed."""
    alice, mallory = two_users
    theirs = await _make_project(session, mallory)

    await _sign_in(client, kv, alice)
    real = await client.get(f"/api/v1/projects/{theirs.id}")
    imaginary = await client.get("/api/v1/projects/99999")

    assert real.status_code == imaginary.status_code == 404


# -- duplicate names across owners -----------------------------------------


async def test_two_users_may_register_the_same_repository_name(
    session: AsyncSession, two_users
):
    """The whole point of dropping the global UNIQUE(name) in 0011."""
    alice, mallory = two_users
    await _make_project(session, alice, "SnapBin/SnapBin")
    await _make_project(session, mallory, "SnapBin/SnapBin")

    from sqlalchemy import func, select

    count = (
        await session.execute(
            select(func.count())
            .select_from(Project)
            .where(Project.name == "SnapBin/SnapBin")
        )
    ).scalar_one()
    assert count == 2


async def test_one_user_may_not_register_the_same_name_twice(
    session: AsyncSession, two_users
):
    from sqlalchemy.exc import IntegrityError

    alice, _ = two_users
    await _make_project(session, alice, "SnapBin/SnapBin")
    with pytest.raises(IntegrityError):
        await _make_project(session, alice, "SnapBin/SnapBin")
    await session.rollback()


# -- local mode -------------------------------------------------------------


async def test_local_mode_still_sees_its_own_projects(
    client: AsyncClient, session: AsyncSession, local_user: User
):
    """AUTH_MODE=local resolves to one implicit user, so nothing changes."""
    await _make_project(session, local_user, "local/repo")
    body = (await client.get("/api/v1/projects")).json()
    assert [p["name"] for p in body] == ["local/repo"]


async def test_local_mode_does_not_see_a_signed_in_users_projects(
    client: AsyncClient, session: AsyncSession, local_user: User
):
    other = await _make_user(session, 2002, "someone")
    await _make_project(session, other, "someone/repo")
    await _make_project(session, local_user, "local/repo")

    body = (await client.get("/api/v1/projects")).json()
    assert [p["name"] for p in body] == ["local/repo"]
