"""Task queries, scoped to an owner through the parent project.

Tasks carry no user_id of their own — ownership is inherited from the
project, so every read joins to `projects` and filters there. A task whose
project belongs to someone else is simply not found.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AgentRun, Project, Task


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, task_id: int, user_id: int) -> Task | None:
        result = await self.session.execute(
            select(Task)
            .join(Project, Project.id == Task.project_id)
            .where(Task.id == task_id, Project.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_with_runs(self, task_id: int, user_id: int) -> Task | None:
        result = await self.session.execute(
            select(Task)
            .join(Project, Project.id == Task.project_id)
            .where(Task.id == task_id, Project.user_id == user_id)
            .options(
                selectinload(Task.runs).selectinload(AgentRun.file_changes),
                selectinload(Task.runs).selectinload(AgentRun.test_results),
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self, user_id: int, project_id: int | None = None
    ) -> list[Task]:
        query = (
            select(Task)
            .join(Project, Project.id == Task.project_id)
            .where(Project.user_id == user_id)
            .order_by(Task.created_at.desc(), Task.id.desc())
            .options(selectinload(Task.runs))
        )
        if project_id is not None:
            query = query.where(Task.project_id == project_id)
        result = await self.session.execute(query)
        return list(result.scalars())

    # -- Worker-side access ------------------------------------------------
    #
    # Background jobs run with no request user. They load by id and then
    # re-derive authorisation from the project row, per the Phase 6 decision
    # that payload values are never treated as current authorisation.

    async def get_unscoped_for_worker(self, task_id: int) -> Task | None:
        return await self.session.get(Task, task_id)

    async def get_with_runs_unscoped_for_worker(self, task_id: int) -> Task | None:
        result = await self.session.execute(
            select(Task)
            .where(Task.id == task_id)
            .options(
                selectinload(Task.runs).selectinload(AgentRun.file_changes),
                selectinload(Task.runs).selectinload(AgentRun.test_results),
            )
        )
        return result.scalar_one_or_none()

    def add(self, task: Task) -> None:
        self.session.add(task)
