from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AgentRun, Task


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, task_id: int) -> Task | None:
        return await self.session.get(Task, task_id)

    async def get_with_runs(self, task_id: int) -> Task | None:
        result = await self.session.execute(
            select(Task)
            .where(Task.id == task_id)
            .options(
                selectinload(Task.runs).selectinload(AgentRun.file_changes),
                selectinload(Task.runs).selectinload(AgentRun.test_results),
            )
        )
        return result.scalar_one_or_none()

    async def list(self, project_id: int | None = None) -> list[Task]:
        query = (
            select(Task)
            .order_by(Task.created_at.desc(), Task.id.desc())
            .options(selectinload(Task.runs))
        )
        if project_id is not None:
            query = query.where(Task.project_id == project_id)
        result = await self.session.execute(query)
        return list(result.scalars())

    def add(self, task: Task) -> None:
        self.session.add(task)
