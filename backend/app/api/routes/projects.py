from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import Queue, get_project_service
from app.models import Project
from app.schemas.analysis import AnalysisRead
from app.schemas.project import (
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectRegister,
    ProjectSettingsUpdate,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

Service = Annotated[ProjectService, Depends(get_project_service)]


def _to_read(project: Project) -> ProjectRead:
    item = ProjectRead.model_validate(project)
    if project.analyses:
        latest = project.analyses[-1]
        item.analysis_status = latest.status
        item.last_analyzed_at = latest.finished_at
        item.primary_language = (latest.languages or [None])[0]
        item.framework = (latest.frameworks or [None])[0]
        item.test_command = latest.test_command
        item.health_score = latest.health_score
    return item


@router.get("", response_model=list[ProjectRead])
async def list_projects(service: Service) -> list[ProjectRead]:
    return [_to_read(p) for p in await service.list_projects()]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, service: Service) -> ProjectRead:
    return ProjectRead.model_validate(await service.create_project(data))


@router.post(
    "/register", response_model=ProjectRead, status_code=status.HTTP_201_CREATED
)
async def register_project(data: ProjectRegister, service: Service) -> ProjectRead:
    return ProjectRead.model_validate(await service.register_project(data))


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: int, service: Service) -> ProjectDetail:
    project = await service.get_project_detail(project_id)
    detail = ProjectDetail(**_to_read(project).model_dump())
    if project.analyses:
        detail.latest_analysis = AnalysisRead.model_validate(project.analyses[-1])
    return detail


@router.patch("/{project_id}/settings", response_model=ProjectRead)
async def update_project_settings(
    project_id: int, data: ProjectSettingsUpdate, service: Service
) -> ProjectRead:
    await service.update_settings(project_id, data)
    return _to_read(await service.get_project_detail(project_id))


@router.post("/{project_id}/analyze", response_model=AnalysisRead)
async def analyze_project(
    project_id: int, service: Service, queue: Queue
) -> AnalysisRead:
    return AnalysisRead.model_validate(
        await service.start_analysis(project_id, queue)
    )
