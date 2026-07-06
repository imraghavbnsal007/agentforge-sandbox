from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models import Project
from app.repositories.project_repo import ProjectRepository
from app.schemas.project import ProjectCreate


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ProjectRepository(session)

    async def create_project(self, data: ProjectCreate) -> Project:
        if await self.repo.get_by_name(data.name) is not None:
            raise ConflictError(f"Project named {data.name!r} already exists")
        project = Project(**data.model_dump())
        self.repo.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def list_projects(self) -> list[Project]:
        return await self.repo.list()
