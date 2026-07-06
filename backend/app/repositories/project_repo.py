from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: int) -> Project | None:
        return await self.session.get(Project, project_id)

    async def get_by_name(self, name: str) -> Project | None:
        result = await self.session.execute(select(Project).where(Project.name == name))
        return result.scalar_one_or_none()

    async def list(self) -> list[Project]:
        result = await self.session.execute(select(Project).order_by(Project.id))
        return list(result.scalars())

    def add(self, project: Project) -> None:
        self.session.add(project)
