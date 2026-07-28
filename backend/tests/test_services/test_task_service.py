import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TaskStatus
from app.core.exceptions import NotFoundError
from app.models import Project, User
from app.schemas.task import TaskCreate
from app.services.task_service import TaskService
from tests.conftest import FakeQueue


async def test_create_task_persists_and_enqueues(
    session: AsyncSession, project: Project, fake_queue: FakeQueue,
    local_user: User,
) -> None:
    service = TaskService(session, fake_queue, local_user)
    task = await service.create_task(
        TaskCreate(project_id=project.id, title="T", request="R")
    )
    assert task.id > 0
    assert task.status == TaskStatus.pending
    assert fake_queue.enqueued == [task.id]


async def test_create_task_missing_project_raises(
    session: AsyncSession, fake_queue: FakeQueue, local_user: User
) -> None:
    service = TaskService(session, fake_queue, local_user)
    with pytest.raises(NotFoundError):
        await service.create_task(TaskCreate(project_id=42, title="T", request="R"))
    assert fake_queue.enqueued == []


async def test_get_task_detail_missing_raises(
    session: AsyncSession, fake_queue: FakeQueue, local_user: User
) -> None:
    service = TaskService(session, fake_queue, local_user)
    with pytest.raises(NotFoundError):
        await service.get_task_detail(42)
