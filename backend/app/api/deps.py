from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.worker.queue import ArqJobQueue, JobQueue


def get_queue(request: Request) -> JobQueue:
    return ArqJobQueue(request.app.state.arq_pool)


DbSession = Annotated[AsyncSession, Depends(get_db)]
Queue = Annotated[JobQueue, Depends(get_queue)]


def get_project_service(session: DbSession) -> ProjectService:
    return ProjectService(session)


def get_task_service(session: DbSession, queue: Queue) -> TaskService:
    return TaskService(session, queue)
