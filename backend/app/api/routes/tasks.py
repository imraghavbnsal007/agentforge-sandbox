from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_task_service
from app.models import Task
from app.schemas.run import AgentRunRead
from app.schemas.task import TaskCreate, TaskDetail, TaskRead
from app.services.task_service import TaskService

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

Service = Annotated[TaskService, Depends(get_task_service)]


def _to_detail(task: Task) -> TaskDetail:
    latest_run = AgentRunRead.model_validate(task.runs[-1]) if task.runs else None
    return TaskDetail(
        **TaskRead.model_validate(task).model_dump(), latest_run=latest_run
    )


@router.get("", response_model=list[TaskRead])
async def list_tasks(service: Service, project_id: int | None = None) -> list[TaskRead]:
    return [TaskRead.model_validate(t) for t in await service.list_tasks(project_id)]


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, service: Service) -> TaskRead:
    return TaskRead.model_validate(await service.create_task(data))


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: int, service: Service) -> TaskDetail:
    return _to_detail(await service.get_task_detail(task_id))
