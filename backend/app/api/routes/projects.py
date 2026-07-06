from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_project_service
from app.schemas.project import ProjectCreate, ProjectRead
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

Service = Annotated[ProjectService, Depends(get_project_service)]


@router.get("", response_model=list[ProjectRead])
async def list_projects(service: Service) -> list[ProjectRead]:
    return [ProjectRead.model_validate(p) for p in await service.list_projects()]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, service: Service) -> ProjectRead:
    return ProjectRead.model_validate(await service.create_project(data))
