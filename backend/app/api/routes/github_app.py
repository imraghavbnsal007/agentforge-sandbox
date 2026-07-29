"""GitHub App installation: starting an install, handling GitHub's setup
redirect, and listing what the signed-in user has installed.

Repository discovery is deliberately absent — that is Phase 6C.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUser, DbSession
from app.api.routes.auth import INSTALL_LANDING
from app.core.config import settings
from app.core.exceptions import InvalidInputError, NotFoundError
from app.schemas.github_app import InstallationRead, InstallationsStatus
from app.services.installation_service import (
    InstallationAccessError,
    InstallationService,
)
from app.services.oauth_github import OAuthStateStore, authorize_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/github", tags=["github-app"])


def _install_url() -> str | None:
    """Where the browser goes to choose an account and repositories."""
    if not settings.github_app_name:
        return None
    return f"https://github.com/apps/{settings.github_app_name}/installations/new"


def _to_read(installation) -> InstallationRead:
    item = InstallationRead.model_validate(installation)
    item.is_active = installation.is_active
    return item


@router.get("/installations", response_model=InstallationsStatus)
async def list_installations(
    user: CurrentUser, db: DbSession
) -> InstallationsStatus:
    installations = await InstallationService(db).list_for_user(user)
    return InstallationsStatus(
        app_configured=settings.github_app_configured(),
        install_url=_install_url(),
        installations=[_to_read(i) for i in installations],
    )


@router.get("/install")
async def start_install(user: CurrentUser) -> RedirectResponse:
    """Send the user to GitHub to install the App."""
    url = _install_url()
    if url is None:
        raise InvalidInputError(
            "GITHUB_APP_NAME is not set — required to build the installation "
            "link."
        )
    return RedirectResponse(url, status_code=307)


@router.get("/setup")
async def installation_setup(
    request: Request,
    user: CurrentUser,
    installation_id: str = "",
    setup_action: str = "",
) -> RedirectResponse:
    """GitHub's Setup URL target, for installs that did not carry an OAuth code.

    We cannot trust `installation_id` from this redirect, and we have no user
    token here to check it against. Rather than storing a token for later,
    we bounce the user through `authorize` to obtain a fresh one — GitHub
    returns immediately without re-prompting if they have already authorized
    the App. The callback then verifies and links the installation.
    """
    try:
        github_installation_id = int(installation_id)
    except (TypeError, ValueError):
        github_installation_id = 0

    if github_installation_id <= 0:
        # A bare setup hit with nothing to verify (e.g. "Configure" with no
        # change) — nothing to do but return the user to the app.
        return RedirectResponse(
            f"{settings.frontend_url.rstrip('/')}{INSTALL_LANDING}",
            status_code=303,
        )

    if setup_action == "request":
        # Org install awaiting an administrator's approval; there is nothing
        # to verify until it is granted.
        return RedirectResponse(
            f"{settings.frontend_url.rstrip('/')}"
            f"{INSTALL_LANDING}?install_pending=1",
            status_code=303,
        )

    if not settings.github_oauth_configured():
        raise InvalidInputError(
            "GitHub sign-in is not configured — set GITHUB_APP_CLIENT_ID and "
            "GITHUB_APP_CLIENT_SECRET to complete installation."
        )

    state = await OAuthStateStore(request.app.state.kv).issue(
        redirect_to=INSTALL_LANDING,
        installation_id=github_installation_id,
    )
    return RedirectResponse(authorize_url(state), status_code=307)


@router.post("/installations/{github_installation_id}/sync",
             response_model=InstallationRead)
async def sync_installation(
    github_installation_id: int, user: CurrentUser, db: DbSession
) -> InstallationRead:
    """Re-read one installation's status from GitHub.

    Scoped to installations the caller already owns; an unknown or foreign id
    is a 404, never a hint that it exists.
    """
    service = InstallationService(db)
    installation = await service.get_by_github_id(github_installation_id)
    if installation is None or not await service.is_linked(user, installation):
        raise NotFoundError("Not found")
    try:
        refreshed = await service.sync_from_github(github_installation_id)
    except InstallationAccessError as exc:
        raise InvalidInputError(str(exc)) from exc
    return _to_read(refreshed)
