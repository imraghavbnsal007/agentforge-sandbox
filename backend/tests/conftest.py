from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_queue
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models import Project, Task


class FakeQueue:
    """Records enqueued task ids instead of talking to Redis."""

    def __init__(self) -> None:
        self.enqueued: list[int] = []
        self.publish_enqueued: list[int] = []

    async def enqueue_run_agent(self, task_id: int) -> None:
        self.enqueued.append(task_id)

    async def enqueue_publish_task(self, task_id: int) -> None:
        self.publish_enqueued.append(task_id)


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
async def client(
    session: AsyncSession, fake_queue: FakeQueue
) -> AsyncIterator[AsyncClient]:
    app = create_app(with_lifespan=False)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_queue] = lambda: fake_queue
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def project(session: AsyncSession) -> Project:
    project = Project(name="Demo Project", description="", repo_path="sample_repo")
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
