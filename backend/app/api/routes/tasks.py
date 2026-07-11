from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_task_service
from app.models import Task
from app.schemas.run import AgentRunRead
from app.schemas.task import TaskCreate, TaskDetail, TaskRead
from app.services.task_service import TaskService

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

Service = Annotated[TaskService, Depends(get_task_service)]


def _to_read(task: Task) -> TaskRead:
    item = TaskRead.model_validate(task)
    if task.runs:
        item.latest_run_mode = task.runs[-1].mode
        item.latest_run_pr_url = task.runs[-1].pr_url
    return item


async def _to_detail(task: Task, service: TaskService) -> TaskDetail:
    runs = [AgentRunRead.model_validate(r) for r in task.runs]
    llm_summary = await service.get_run_llm_summary([r.id for r in task.runs])
    for run_read, run_orm in zip(runs, task.runs):
        if run_orm.id in llm_summary:
            run_read.llm_provider, run_read.llm_model = llm_summary[run_orm.id]
    return TaskDetail(
        **_to_read(task).model_dump(),
        latest_run=runs[-1] if runs else None,
        runs=runs,
    )


@router.get("", response_model=list[TaskRead])
async def list_tasks(service: Service, project_id: int | None = None) -> list[TaskRead]:
    return [_to_read(t) for t in await service.list_tasks(project_id)]


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, service: Service) -> TaskRead:
    return TaskRead.model_validate(await service.create_task(data))


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: int, service: Service) -> TaskDetail:
    return await _to_detail(await service.get_task_detail(task_id), service)


@router.post("/{task_id}/retry", response_model=TaskRead)
async def retry_task(task_id: int, service: Service) -> TaskRead:
    return TaskRead.model_validate(await service.retry_task(task_id))


@router.post("/{task_id}/approve", response_model=TaskRead)
async def approve_task(task_id: int, service: Service) -> TaskRead:
    return TaskRead.model_validate(await service.approve_task(task_id))


@router.post("/{task_id}/reject", response_model=TaskRead)
async def reject_task(task_id: int, service: Service) -> TaskRead:
    return TaskRead.model_validate(await service.reject_task(task_id))
