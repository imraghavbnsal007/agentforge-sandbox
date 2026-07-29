"""GitHub sign-in, sign-out, and session introspection.

These routes are intentionally NOT behind require_user — they are how a
session comes into existence.
"""

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app.api.deps import (
    AuthRateLimiter,
    CurrentSession,
    DbSession,
    OptionalUser,
    Sessions,
    Users,
)
from app.core.audit import (
    LOGIN_FAILED,
    LOGIN_STARTED,
    LOGIN_SUCCEEDED,
    LOGOUT,
    audit,
)
from app.core.config import settings
from app.core.exceptions import InvalidInputError
from app.core.security import (
    clear_session_cookies,
    client_ip,
    set_session_cookies,
)
from app.schemas.auth import AuthStatus, UserRead
from app.services.kv_store import KVStore
from app.services.oauth_github import (
    GitHubOAuthClient,
    OAuthError,
    OAuthStateStore,
    authorize_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Where a user lands once an installation has been dealt with. The repository
# picker lives here, so it is the page that can actually act on the result.
INSTALL_LANDING = "/projects"

# Overridable in tests so no live GitHub call is ever made.
_oauth_client_factory = GitHubOAuthClient


def _state_store(kv: KVStore) -> OAuthStateStore:
    return OAuthStateStore(kv)


def _safe_redirect(target: str) -> str:
    """Only ever redirect to a path on our own frontend.

    An absolute URL from the query string would be an open redirect, so
    anything that is not a single-slash-prefixed path is discarded.
    """
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    return f"{settings.frontend_url.rstrip('/')}{target}"


@router.get("/me", response_model=AuthStatus)
async def read_me(user: OptionalUser) -> AuthStatus:
    return AuthStatus(
        auth_mode=settings.auth_mode,
        authenticated=user is not None,
        login_available=settings.github_oauth_configured(),
        user=UserRead.model_validate(user) if user is not None else None,
    )


@router.get("/github/login")
async def github_login(
    request: Request,
    limiter: AuthRateLimiter,
    redirect_to: str = "/",
) -> RedirectResponse:
    """Start the OAuth round trip: issue single-use state, bounce to GitHub."""
    ip = client_ip(request)
    await limiter.check("auth_login", ip)

    if not settings.github_oauth_configured():
        raise InvalidInputError(
            "GitHub sign-in is not configured — set GITHUB_APP_CLIENT_ID and "
            "GITHUB_APP_CLIENT_SECRET."
        )
    if not redirect_to.startswith("/") or redirect_to.startswith("//"):
        redirect_to = "/"

    state = await _state_store(request.app.state.kv).issue(redirect_to)
    audit(LOGIN_STARTED, ip=ip)
    return RedirectResponse(authorize_url(state), status_code=307)


@router.get("/github/callback")
async def github_callback(
    request: Request,
    sessions: Sessions,
    users: Users,
    limiter: AuthRateLimiter,
    db: DbSession,
    code: str = "",
    state: str = "",
    error: str = "",
    installation_id: str = "",
    setup_action: str = "",
) -> RedirectResponse:
    """Finish sign-in: validate state, exchange the code, create a session.

    The access token obtained here is used to read the profile and — when the
    round trip also carried a GitHub App installation — to verify that the
    installation really belongs to this user. It is discarded immediately
    afterwards and is never stored, logged, or reused for repository access.
    """
    ip = client_ip(request)
    await limiter.check("auth_callback", ip)

    if error:
        audit(LOGIN_FAILED, reason="github_error", detail=error, ip=ip)
        raise InvalidInputError(f"GitHub sign-in was cancelled or failed: {error}")

    # An install started on github.com lands here with no `state` — the user
    # never passed through /github/login, so there was no round trip of ours
    # to carry one. This is normal for GitHub Apps that request user
    # authorization during installation, and for "Save" on the repository
    # access screen. Trusting a stateless callback would reopen sign-in to
    # CSRF, so we start a proper round trip carrying the installation id
    # instead. GitHub returns immediately without re-prompting an already
    # authorized user, and that second callback takes the verified path below.
    if not state and setup_action:
        return await _restart_from_install(request, ip, installation_id, setup_action)

    # State is validated before the code is touched, and burned on read so a
    # replayed callback cannot mint a second session.
    oauth_state = await _state_store(request.app.state.kv).consume(state)
    if oauth_state is None:
        audit(LOGIN_FAILED, reason="invalid_state", ip=ip)
        raise InvalidInputError(
            "Sign-in link is invalid or has expired — please try again."
        )
    if not code:
        audit(LOGIN_FAILED, reason="missing_code", ip=ip)
        raise InvalidInputError("GitHub did not return an authorization code.")

    # GitHub appends installation_id when the App was installed as part of
    # this authorization; the state carries it when we started the round trip
    # ourselves from the setup URL.
    pending_installation = _coerce_installation_id(installation_id) or (
        oauth_state.installation_id
    )

    client = _oauth_client_factory()
    redirect_to = oauth_state.redirect_to
    try:
        access_token = await client.exchange_code(code)
        profile = await client.fetch_profile(access_token)

        user = await users.upsert_from_github(profile)
        session = await sessions.create(user.id, user.github_login)
        audit(LOGIN_SUCCEEDED, user_id=user.id, github_login=user.github_login, ip=ip)

        if pending_installation is not None:
            redirect_to = await _link_installation(
                request, db, user, pending_installation, access_token, redirect_to
            )
    except OAuthError as exc:
        audit(LOGIN_FAILED, reason="oauth_failed", detail=str(exc), ip=ip)
        raise InvalidInputError(str(exc)) from exc
    finally:
        # Identity only. Nothing downstream may reuse this token, and it is
        # never written anywhere.
        access_token = ""

    response = RedirectResponse(_safe_redirect(redirect_to), status_code=303)
    set_session_cookies(response, session.session_id, session.csrf_token)
    return response


def _coerce_installation_id(raw: str) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def _restart_from_install(
    request: Request, ip: str, installation_id: str, setup_action: str
) -> RedirectResponse:
    """Turn a stateless install redirect into a round trip we started."""
    github_installation_id = _coerce_installation_id(installation_id)

    if setup_action == "request":
        # An organisation install waiting on an owner to approve it. There is
        # nothing to verify until that happens.
        return RedirectResponse(
            _safe_redirect(f"{INSTALL_LANDING}?install_pending=1"), status_code=303
        )

    if github_installation_id is None or not settings.github_oauth_configured():
        # Nothing actionable came back (e.g. "Configure" closed without a
        # change). Put the user back on the page they came from.
        return RedirectResponse(_safe_redirect(INSTALL_LANDING), status_code=303)

    state = await _state_store(request.app.state.kv).issue(
        redirect_to=INSTALL_LANDING, installation_id=github_installation_id
    )
    audit(LOGIN_STARTED, ip=ip, source="github_install")
    return RedirectResponse(authorize_url(state), status_code=307)


async def _link_installation(
    request: Request,
    db,
    user,
    github_installation_id: int,
    access_token: str,
    redirect_to: str,
) -> str:
    """Verify and record an installation using the just-issued user token.

    A failure here must not sink an otherwise valid sign-in: the user is
    signed in either way and sent somewhere that explains the problem.
    """
    from app.services.installation_service import (
        InstallationAccessError,
        InstallationService,
    )

    try:
        installation = await InstallationService(db).link_installation_for_user(
            user, github_installation_id, access_token
        )
    except InstallationAccessError:
        return f"{INSTALL_LANDING}?install_error=not_available"
    except Exception:
        logger.exception(
            "Installation %s could not be linked after sign-in",
            github_installation_id,
        )
        return f"{INSTALL_LANDING}?install_error=verification_failed"

    await _sync_repositories(request, db, installation)
    return redirect_to if redirect_to != "/" else INSTALL_LANDING


async def _sync_repositories(request: Request, db, installation) -> None:
    """Populate the repository cache for a freshly linked installation.

    The picker reads the local cache, which is empty the moment a link is
    created — without this the user lands on "no repositories" straight after
    granting access to some. Best-effort: a failure leaves the Refresh button
    to do the same job, so it must not break sign-in.
    """
    from app.services.github_app_token_service import GitHubAppTokenService
    from app.services.repository_discovery import RepositoryDiscoveryService

    try:
        discovery = RepositoryDiscoveryService(
            db, GitHubAppTokenService(request.app.state.kv)
        )
        await discovery.sync_installation(installation)
    except Exception:
        logger.warning(
            "Initial repository sync failed for installation %s",
            installation.github_installation_id,
            exc_info=True,
        )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    sessions: Sessions,
    session_data: CurrentSession,
) -> Response:
    """Destroy the session server-side and clear the cookies.

    Idempotent: signing out without a session is a success, not an error.
    """
    if session_data is not None:
        await sessions.delete(session_data.session_id)
        audit(
            LOGOUT,
            user_id=session_data.user_id,
            github_login=session_data.github_login,
            ip=client_ip(request),
        )
    result = Response(status_code=204)
    clear_session_cookies(result)
    return result
