from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Project, ProjectAnalysis


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: int) -> Project | None:
        return await self.session.get(Project, project_id)

    async def get_by_name(self, name: str) -> Project | None:
        result = await self.session.execute(select(Project).where(Project.name == name))
        return result.scalar_one_or_none()

    async def get_by_github_repo(self, owner: str, repo: str) -> Project | None:
        result = await self.session.execute(
            select(Project).where(
                Project.github_owner == owner, Project.github_repo == repo
            )
        )
        return result.scalars().first()

    async def list(self) -> list[Project]:
        result = await self.session.execute(
            select(Project)
            .order_by(Project.id)
            .options(selectinload(Project.analyses))
        )
        return list(result.scalars())

    async def get_with_analyses(self, project_id: int) -> Project | None:
        result = await self.session.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(
                selectinload(Project.analyses).selectinload(
                    ProjectAnalysis.file_summaries
                ),
                selectinload(Project.analyses).selectinload(
                    ProjectAnalysis.suggestions
                ),
            )
        )
        return result.scalar_one_or_none()

    def add(self, project: Project) -> None:
        self.session.add(project)
