"""Project queries, all scoped to an owner.

Every method takes `user_id` and filters on it. There is deliberately no
unscoped read: a missing filter is the classic multi-tenancy bug, so the
signature makes it impossible to forget.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Project, ProjectAnalysis


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: int, user_id: int) -> Project | None:
        result = await self.session.execute(
            select(Project).where(
                Project.id == project_id, Project.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str, user_id: int) -> Project | None:
        result = await self.session.execute(
            select(Project).where(
                Project.name == name, Project.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_github_repo(
        self, owner: str, repo: str, user_id: int
    ) -> Project | None:
        result = await self.session.execute(
            select(Project).where(
                Project.github_owner == owner,
                Project.github_repo == repo,
                Project.user_id == user_id,
            )
        )
        return result.scalars().first()

    async def get_by_github_repository_id(
        self, github_repository_id: int, user_id: int
    ) -> Project | None:
        result = await self.session.execute(
            select(Project).where(
                Project.github_repository_id == github_repository_id,
                Project.user_id == user_id,
            )
        )
        return result.scalars().first()

    async def list(self, user_id: int) -> list[Project]:
        result = await self.session.execute(
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.id)
            .options(selectinload(Project.analyses))
        )
        return list(result.scalars())

    async def get_with_analyses(
        self, project_id: int, user_id: int
    ) -> Project | None:
        result = await self.session.execute(
            select(Project)
            .where(Project.id == project_id, Project.user_id == user_id)
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
