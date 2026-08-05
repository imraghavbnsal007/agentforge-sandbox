from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.services.github_app_token_service import GitHubAppTokenService
    from app.services.installation_service import InstallationService
    from app.services.execution_lock import CancellationSignal
    from app.services.repository_discovery import RepositoryDiscoveryService
    from app.services.task_events import TaskEventService

from app.core.audit import SESSION_REJECTED, audit
from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.ratelimit import RateLimiter
from app.core.security import client_ip, read_session_cookie
from app.db.session import get_db
from app.models.user import User
from app.services.kv_store import KVStore
from app.services.project_service import ProjectService
from app.services.session_store import SessionData, SessionStore
from app.services.task_service import TaskService
from app.services.user_service import UserService
from app.worker.queue import ArqJobQueue, JobQueue


def get_queue(request: Request) -> JobQueue:
    return ArqJobQueue(request.app.state.arq_pool)


def get_kv(request: Request) -> KVStore:
    return request.app.state.kv


DbSession = Annotated[AsyncSession, Depends(get_db)]
Queue = Annotated[JobQueue, Depends(get_queue)]
KV = Annotated[KVStore, Depends(get_kv)]


def get_session_store(kv: KV) -> SessionStore:
    return SessionStore(kv, ttl_seconds=settings.session_ttl_seconds)


Sessions = Annotated[SessionStore, Depends(get_session_store)]


def get_auth_rate_limiter(kv: KV) -> RateLimiter:
    return RateLimiter(
        kv,
        limit=settings.auth_rate_limit_requests,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )


AuthRateLimiter = Annotated[RateLimiter, Depends(get_auth_rate_limiter)]


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


Users = Annotated[UserService, Depends(get_user_service)]


async def get_current_session(
    request: Request, sessions: Sessions
) -> SessionData | None:
    """Resolve the session cookie, if any. Never raises."""
    session_id = read_session_cookie(request)
    if not session_id:
        return None
    data = await sessions.get(session_id)
    if data is None:
        audit(
            SESSION_REJECTED,
            reason="unknown_or_expired",
            ip=client_ip(request),
            path=request.url.path,
        )
    return data


CurrentSession = Annotated[SessionData | None, Depends(get_current_session)]


async def get_current_user(
    request: Request,
    users: Users,
    session_data: CurrentSession,
) -> User | None:
    """The authenticated user, or None.

    In AUTH_MODE=local there is no sign-in: every request resolves to the
    default local user, which is what preserves the single-user workflow and
    keeps existing routes and tests working untouched.
    """
    if not settings.is_github_app_mode():
        return await users.get_or_create_local_user()
    if session_data is None:
        return None
    user = await users.get_by_id(session_data.user_id)
    if user is None:
        # Session outlived the account row.
        audit(
            SESSION_REJECTED,
            reason="user_missing",
            user_id=session_data.user_id,
            ip=client_ip(request),
        )
    return user


OptionalUser = Annotated[User | None, Depends(get_current_user)]


async def require_user(user: OptionalUser) -> User:
    """Route guard: 401 unless the caller is authenticated.

    Applied at router level in main.py to every data router, so no individual
    route has to remember it.
    """
    if user is None:
        raise UnauthorizedError("Sign in with GitHub to continue.")
    return user


CurrentUser = Annotated[User, Depends(require_user)]


def ensure_owned(obj: Any, user: User) -> Any:
    """Central ownership check for user-scoped rows.

    Raises NotFoundError — deliberately 404, never 403 — so a caller cannot
    probe for the existence of another user's objects.

    Phase 6A ships and tests this helper; it is wired into the project and
    task routes in Phase 6C, once migration 0011 adds Project.user_id. Rows
    with no owner column are treated as visible, which is what keeps local
    mode unchanged in the interim.
    """
    owner_id = getattr(obj, "user_id", None)
    if owner_id is not None and owner_id != user.id:
        raise NotFoundError("Not found")
    return obj


def get_token_service(kv: KV) -> "GitHubAppTokenService":
    from app.services.github_app_token_service import GitHubAppTokenService

    return GitHubAppTokenService(kv)


TokenService = Annotated["GitHubAppTokenService", Depends(get_token_service)]


def get_installation_service(session: DbSession) -> "InstallationService":
    from app.services.installation_service import InstallationService

    return InstallationService(session)


Installations = Annotated["InstallationService", Depends(get_installation_service)]


def get_project_service(session: DbSession, user: CurrentUser) -> ProjectService:
    return ProjectService(session, user)


def get_events_service(session: DbSession, kv: KV) -> "TaskEventService":
    from app.services.task_events import TaskEventService

    return TaskEventService(session, kv)


Events = Annotated["TaskEventService", Depends(get_events_service)]


def get_cancellation(kv: KV) -> "CancellationSignal":
    from app.services.execution_lock import CancellationSignal

    return CancellationSignal(kv)


Cancellation = Annotated["CancellationSignal", Depends(get_cancellation)]


def get_task_service(
    session: DbSession,
    queue: Queue,
    user: CurrentUser,
    kv: KV,
) -> TaskService:
    from app.services.execution_lock import CancellationSignal
    from app.services.task_events import TaskEventService

    return TaskService(
        session,
        queue,
        user,
        cancellation=CancellationSignal(kv),
        events=TaskEventService(session, kv),
    )


def get_discovery_service(
    session: DbSession, token_service: TokenService
) -> "RepositoryDiscoveryService":
    from app.services.execution_lock import CancellationSignal
    from app.services.repository_discovery import RepositoryDiscoveryService
    from app.services.task_events import TaskEventService

    return RepositoryDiscoveryService(session, token_service)


Discovery = Annotated[
    "RepositoryDiscoveryService", Depends(get_discovery_service)
]
Service = Annotated[ProjectService, Depends(get_project_service)]
Tasks = Annotated[TaskService, Depends(get_task_service)]


def forbid_in_showcase() -> None:
    """Refuse an operation that a public demonstration must not expose.

    Applied to the endpoints that reach outside the demo: publishing to
    GitHub, registering or cloning a repository, running analysis (real API
    spend), and changing a project's AI settings. Enforced server-side, not
    by hiding buttons — the UI hides them too, but a visitor with curl is
    the case that matters.
    """
    if settings.showcase_mode:
        raise ForbiddenError(
            "This is a portfolio demonstration of AgentForge. Creating and "
            "watching tasks against the bundled sample repository is enabled; "
            "publishing to GitHub, registering repositories and repository "
            "analysis are not. Run it locally to use the full workflow."
        )


#: Attach with `dependencies=[ShowcaseGuard]` on a route.
ShowcaseGuard = Depends(forbid_in_showcase)
