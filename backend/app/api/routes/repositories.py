"""Repository discovery: what the caller's GitHub App installations grant.

This replaces "paste any GitHub URL" in github_app mode. Every response is
scoped to the caller's own installations.
"""

import logging

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, Discovery, Service, ShowcaseGuard
from app.core.config import settings
from app.core.exceptions import ForbiddenError
from app.schemas.project import ProjectRead
from app.schemas.repository import (
    RepositoryList,
    RepositoryRead,
    RepositoryRegister,
)
from app.services.installation_service import (
    InstallationAccessError,
    InstallationService,
)
from app.services.repository_discovery import DiscoveredRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])


def _install_url() -> str | None:
    if not settings.github_app_name:
        return None
    return f"https://github.com/apps/{settings.github_app_name}/installations/new"


def _to_read(item: DiscoveredRepository) -> RepositoryRead:
    repository, installation = item.repository, item.installation
    return RepositoryRead(
        github_repository_id=repository.github_repository_id,
        owner=repository.owner,
        name=repository.name,
        full_name=repository.full_name,
        default_branch=repository.default_branch,
        private=repository.private,
        archived=repository.archived,
        disabled=repository.disabled,
        is_usable=repository.is_usable,
        last_synced_at=repository.last_synced_at,
        installation_id=installation.github_installation_id,
        installation_account=installation.account_login,
        installation_active=installation.is_active,
        is_registered=item.is_registered,
        project_id=item.registered_project_id,
    )


async def _build_list(user, discovery, installations) -> RepositoryList:
    found = await discovery.list_for_user(user)
    return RepositoryList(
        app_configured=settings.github_app_configured(),
        install_url=_install_url(),
        has_installations=bool(installations),
        repositories=[_to_read(item) for item in found],
    )


@router.get("", response_model=RepositoryList)
async def list_repositories(
    user: CurrentUser, discovery: Discovery
) -> RepositoryList:
    """Cached view of everything the caller's installations grant."""
    installations = await InstallationService(discovery.session).list_for_user(user)
    return await _build_list(user, discovery, installations)


@router.post("/refresh", response_model=RepositoryList)
async def refresh_repositories(
    user: CurrentUser, discovery: Discovery
) -> RepositoryList:
    """Re-read the grant list from GitHub, then return the refreshed view.

    A sync removes repositories GitHub no longer reports, so revoked access
    disappears here immediately.
    """
    installations = await InstallationService(discovery.session).list_for_user(user)
    try:
        await discovery.sync_all_for_user(user)
    except InstallationAccessError as exc:
        raise ForbiddenError(str(exc)) from exc
    return await _build_list(user, discovery, installations)


@router.post(
    "/register",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[ShowcaseGuard],
)
async def register_repository(
    data: RepositoryRegister,
    service: Service,
    discovery: Discovery,
) -> ProjectRead:
    """Register a granted repository as a project.

    Authorisation lives in `discovery.find_granted`: the repository must be
    currently granted to one of the caller's active installations, so a
    fabricated id is refused rather than registered.
    """
    try:
        project = await service.register_from_installation(
            data.github_repository_id, discovery
        )
    except InstallationAccessError as exc:
        raise ForbiddenError(str(exc)) from exc
    return ProjectRead.model_validate(project)
