from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import Events, KV, get_task_service
from app.models import Task
from app.schemas.run import AgentRunRead
from app.schemas.task import (
    TaskCreate,
    TaskDetail,
    TaskEventPage,
    TaskEventRead,
    TaskRead,
)
from app.services.run_usage import usage_for_run
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
        run_read.usage = (
            await usage_for_run(service.session, run_orm)
        ).as_dict()
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


@router.post(
    "/{task_id}/duplicate",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_task(task_id: int, service: Service) -> TaskRead:
    """Run a finished task again as a brand-new task.

    Completed tasks stay terminal; this is how a user repeats the work without
    the finished result becoming ambiguous.
    """
    return TaskRead.model_validate(await service.duplicate_task(task_id))


@router.post("/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(task_id: int, service: Service) -> TaskRead:
    """Ask the worker to stop at its next safe checkpoint.

    User-scoped like every other task route: another user's task is a 404,
    not a 403.
    """
    return TaskRead.model_validate(await service.cancel_task(task_id))


@router.get("/{task_id}/events", response_model=TaskEventPage)
async def list_task_events(
    task_id: int,
    service: Service,
    events: Events,
    after_id: int = 0,
    limit: int = 200,
) -> TaskEventPage:
    """Ordered event history after a cursor.

    This is how a client that missed live events catches up — the stream is a
    convenience, this is the source of truth.
    """
    # Ownership is enforced by resolving the task through the scoped service.
    await service.get_task_detail(task_id)
    limit = max(1, min(limit, 500))
    records = await events.history(task_id, after_id=after_id, limit=limit)
    return TaskEventPage(
        events=[TaskEventRead.model_validate(r) for r in records],
        next_cursor=records[-1].id if len(records) == limit else None,
    )


@router.get("/{task_id}/stream")
async def stream_task_events(
    task_id: int,
    request: Request,
    service: Service,
    events: Events,
    kv: KV,
    last_event_id: int = 0,
):
    """Server-sent events for one task.

    Replay-then-follow: everything after the cursor is sent immediately, then
    new events as they arrive. A reconnecting client passes Last-Event-ID and
    loses nothing.

    Heartbeat comments keep reverse proxies from closing an idle connection.
    """
    from app.api.sse import task_event_stream

    await service.get_task_detail(task_id)  # 404s for someone else's task
    cursor = last_event_id or _last_event_id_header(request)
    return StreamingResponse(
        task_event_stream(task_id, events, kv, after_id=cursor, request=request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Nginx buffers by default, which would defeat streaming entirely.
            "X-Accel-Buffering": "no",
        },
    )


def _last_event_id_header(request: Request) -> int:
    """The browser resends its cursor here automatically on reconnect."""
    try:
        return int(request.headers.get("Last-Event-ID", "0"))
    except (TypeError, ValueError):
        return 0
