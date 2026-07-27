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
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    """Finish sign-in: validate state, exchange the code, create a session.

    The access token obtained here is used once to read the profile and is
    then discarded — it is never stored or logged.
    """
    ip = client_ip(request)
    await limiter.check("auth_callback", ip)

    if error:
        audit(LOGIN_FAILED, reason="github_error", detail=error, ip=ip)
        raise InvalidInputError(f"GitHub sign-in was cancelled or failed: {error}")

    # State is validated before the code is touched, and burned on read so a
    # replayed callback cannot mint a second session.
    redirect_to = await _state_store(request.app.state.kv).consume(state)
    if redirect_to is None:
        audit(LOGIN_FAILED, reason="invalid_state", ip=ip)
        raise InvalidInputError(
            "Sign-in link is invalid or has expired — please try again."
        )
    if not code:
        audit(LOGIN_FAILED, reason="missing_code", ip=ip)
        raise InvalidInputError("GitHub did not return an authorization code.")

    client = _oauth_client_factory()
    try:
        access_token = await client.exchange_code(code)
        profile = await client.fetch_profile(access_token)
    except OAuthError as exc:
        audit(LOGIN_FAILED, reason="oauth_failed", detail=str(exc), ip=ip)
        raise InvalidInputError(str(exc)) from exc
    finally:
        # Identity only. Nothing downstream may reuse this token.
        access_token = ""

    user = await users.upsert_from_github(profile)
    session = await sessions.create(user.id, user.github_login)
    audit(
        LOGIN_SUCCEEDED,
        user_id=user.id,
        github_login=user.github_login,
        ip=ip,
    )

    response = RedirectResponse(_safe_redirect(redirect_to), status_code=303)
    set_session_cookies(response, session.session_id, session.csrf_token)
    return response


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
