from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_queue
from app.core.security import CSRF_HEADER
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models import Project, Task, User
from app.services.kv_store import InMemoryKVStore
from app.services.session_store import SessionStore


@pytest.fixture(autouse=True)
def _neutral_github_settings(monkeypatch: pytest.MonkeyPatch):
    """Isolate tests from the host/container's real GitHub configuration.

    Tests that need an allowlist or token set their own via monkeypatch.
    Auth defaults to local mode — the same default the product ships — so
    every pre-Phase-6A test keeps exercising unauthenticated routes.
    """
    from app.core.config import settings
    from app.core.enums import AuthMode

    monkeypatch.setattr(settings, "github_allowed_repos", "")
    monkeypatch.setattr(settings, "auth_mode", AuthMode.local)
    # Also neutralise GitHub App configuration. Without this, tests pass or
    # fail depending on whether the developer running them happens to have a
    # real App configured in .env — which is exactly the kind of ambient
    # dependency that makes a suite untrustworthy.
    for attribute in (
        "github_app_id",
        "github_app_private_key_path",
        "github_app_client_id",
        "github_app_client_secret",
        "github_app_name",
        "github_app_webhook_secret",
        "github_app_commit_name",
        "github_app_commit_email",
    ):
        monkeypatch.setattr(settings, attribute, "")
    yield


class FakeQueue:
    """Records enqueued task ids instead of talking to Redis."""

    def __init__(self) -> None:
        self.enqueued: list[int] = []
        self.publish_enqueued: list[int] = []
        self.analyze_enqueued: list[int] = []

    async def enqueue_run_agent(self, task_id: int) -> None:
        self.enqueued.append(task_id)

    async def enqueue_publish_task(self, task_id: int) -> None:
        self.publish_enqueued.append(task_id)

    async def enqueue_analyze_project(self, analysis_id: int) -> None:
        self.analyze_enqueued.append(analysis_id)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def fake_queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def kv() -> InMemoryKVStore:
    """Session/OAuth-state/rate-limit backing store for one test."""
    return InMemoryKVStore()


@pytest.fixture
async def client(
    session: AsyncSession, fake_queue: FakeQueue, kv: InMemoryKVStore
) -> AsyncIterator[AsyncClient]:
    app = create_app(with_lifespan=False)
    app.state.kv = kv
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_queue] = lambda: fake_queue
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def signed_in(
    client: AsyncClient, session: AsyncSession, kv: InMemoryKVStore
) -> tuple[AsyncClient, User]:
    """A client holding a real session cookie for a real user row.

    Used by github_app-mode tests; builds the session through SessionStore so
    the cookie/CSRF pairing matches production exactly.
    """
    from app.core.config import settings

    user = User(github_user_id=4242, github_login="octocat", display_name="Octocat")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    store = SessionStore(kv, ttl_seconds=settings.session_ttl_seconds)
    data = await store.create(user.id, user.github_login)
    client.cookies.set(settings.session_cookie_name, data.session_id)
    client.headers[CSRF_HEADER] = data.csrf_token
    return client, user


@pytest.fixture
async def local_user(session: AsyncSession) -> User:
    """The AUTH_MODE=local account every unauthenticated request resolves to.

    Created through the same service the application uses, so tests and
    production agree on what the local user is.
    """
    from app.services.user_service import UserService

    return await UserService(session).get_or_create_local_user()


@pytest.fixture
async def project(session: AsyncSession, local_user: User) -> Project:
    project = Project(
        user_id=local_user.id,
        name="Demo Project",
        description="",
        repo_path="sample_repo",
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@pytest.fixture
async def task(session: AsyncSession, project: Project) -> Task:
    task = Task(
        project_id=project.id,
        title="Add multiply function",
        request="Add multiply(a, b) to the calculator.",
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task
