"""Sign-in, sign-out, route protection, and CSRF at the HTTP boundary.

No test makes a live GitHub call — the OAuth client is replaced wholesale.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AuthMode
from app.core.security import CSRF_HEADER
from app.models import User
from app.services.kv_store import InMemoryKVStore
from app.services.oauth_github import GitHubProfile, OAuthError, OAuthStateStore

PROTECTED_PATHS = [
    "/api/v1/projects",
    "/api/v1/tasks",
    "/api/v1/usage",
    "/api/v1/llm/options",
]


class FakeOAuthClient:
    """Scripted stand-in for GitHubOAuthClient."""

    profile = GitHubProfile(
        github_user_id=4242,
        github_login="octocat",
        avatar_url="https://avatars.example/o.png",
        display_name="The Octocat",
        email="octocat@example.com",
    )
    exchange_error: Exception | None = None
    exchanged_codes: list[str] = []

    async def exchange_code(self, code: str) -> str:
        type(self).exchanged_codes.append(code)
        if type(self).exchange_error is not None:
            raise type(self).exchange_error
        return "gho_never_persist_me"

    async def fetch_profile(self, token: str) -> GitHubProfile:
        return type(self).profile


@pytest.fixture
def fake_oauth(monkeypatch: pytest.MonkeyPatch) -> type[FakeOAuthClient]:
    FakeOAuthClient.exchange_error = None
    FakeOAuthClient.exchanged_codes = []
    monkeypatch.setattr(
        "app.api.routes.auth._oauth_client_factory", FakeOAuthClient
    )
    return FakeOAuthClient


@pytest.fixture
def github_app_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_client_id", "cid")
    monkeypatch.setattr(settings, "github_app_client_secret", "secret")


# -- local mode: nothing changes -------------------------------------------


async def test_local_mode_resolves_a_user_without_signing_in(client: AsyncClient):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["auth_mode"] == "local"
    assert body["authenticated"] is True
    assert body["user"]["github_login"] == "local"
    assert body["user"]["is_local"] is True


@pytest.mark.parametrize("path", PROTECTED_PATHS)
async def test_local_mode_leaves_protected_routes_open(
    client: AsyncClient, path: str
):
    assert (await client.get(path)).status_code == 200


async def test_local_mode_allows_writes_without_a_csrf_token(
    client: AsyncClient, project
):
    """No session cookie means no ambient authority, so CSRF does not apply —
    this is what keeps the pre-Phase-6A suite green."""
    response = await client.post(
        "/api/v1/tasks",
        json={"project_id": project.id, "title": "T", "request": "do it"},
    )
    assert response.status_code == 201


# -- github_app mode: locked down ------------------------------------------


@pytest.mark.parametrize("path", PROTECTED_PATHS)
async def test_github_app_mode_rejects_anonymous_reads(
    client: AsyncClient, github_app_mode, path: str
):
    response = await client.get(path)
    assert response.status_code == 401
    assert "Sign in" in response.json()["detail"]


async def test_github_app_mode_reports_unauthenticated_on_me(
    client: AsyncClient, github_app_mode
):
    body = (await client.get("/api/v1/auth/me")).json()
    assert body["authenticated"] is False
    assert body["user"] is None
    assert body["login_available"] is True


async def test_github_app_mode_reports_login_unavailable_without_credentials(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_client_id", "")
    assert (await client.get("/api/v1/auth/me")).json()["login_available"] is False


async def test_signed_in_user_reaches_protected_routes(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    client, user = signed_in
    assert (await client.get("/api/v1/projects")).status_code == 200
    body = (await client.get("/api/v1/auth/me")).json()
    assert body["authenticated"] is True
    assert body["user"]["github_login"] == user.github_login


async def test_unknown_session_cookie_is_rejected(
    client: AsyncClient, github_app_mode
):
    client.cookies.set(settings.session_cookie_name, "not-a-real-session")
    assert (await client.get("/api/v1/projects")).status_code == 401


async def test_session_for_a_deleted_user_is_rejected(
    signed_in: tuple[AsyncClient, User], session: AsyncSession, github_app_mode
):
    client, user = signed_in
    await session.delete(user)
    await session.commit()
    assert (await client.get("/api/v1/projects")).status_code == 401


async def test_expired_session_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    kv: InMemoryKVStore,
    github_app_mode,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services.session_store import SessionStore

    user = User(github_user_id=7, github_login="ghost")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    expired = await SessionStore(kv, ttl_seconds=0).create(user.id, "ghost")
    client.cookies.set(settings.session_cookie_name, expired.session_id)
    assert (await client.get("/api/v1/projects")).status_code == 401


# -- login ------------------------------------------------------------------


async def test_login_redirects_to_github_with_state(
    client: AsyncClient, github_app_mode, kv: InMemoryKVStore
):
    response = await client.get("/api/v1/auth/github/login", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=cid" in location
    assert "state=" in location
    assert kv.keys_matching("agentforge:oauth_state:*")


async def test_login_without_oauth_credentials_is_a_clear_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_app_client_id", "")
    monkeypatch.setattr(settings, "github_app_client_secret", "")
    response = await client.get("/api/v1/auth/github/login", follow_redirects=False)
    assert response.status_code == 422
    assert "GITHUB_APP_CLIENT_ID" in response.json()["detail"]


async def test_login_refuses_an_absolute_redirect_target(
    client: AsyncClient, github_app_mode, kv: InMemoryKVStore
):
    """An open redirect would let a phishing page harvest a fresh session."""
    await client.get(
        "/api/v1/auth/github/login?redirect_to=https://evil.example/steal",
        follow_redirects=False,
    )
    state_key = kv.keys_matching("agentforge:oauth_state:*")[0]
    assert "evil.example" not in (await kv.get(state_key) or "")


# -- callback ---------------------------------------------------------------


async def _issue_state(kv: InMemoryKVStore, redirect_to: str = "/") -> str:
    return await OAuthStateStore(kv).issue(redirect_to)


async def test_callback_creates_a_user_and_sets_cookies(
    client: AsyncClient,
    github_app_mode,
    fake_oauth,
    kv: InMemoryKVStore,
    session: AsyncSession,
):
    state = await _issue_state(kv, "/projects")
    response = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:3000/projects"

    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(
        c for c in cookies if c.startswith(settings.session_cookie_name)
    )
    csrf_cookie = next(c for c in cookies if c.startswith(settings.csrf_cookie_name))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie.replace("Lax", "lax")
    # The CSRF mirror must be readable by the frontend.
    assert "HttpOnly" not in csrf_cookie

    from app.services.user_service import UserService

    assert await UserService(session).get_by_github_user_id(4242) is not None


async def test_callback_is_not_secure_flagged_in_local_http_development(
    client: AsyncClient, github_app_mode, fake_oauth, kv: InMemoryKVStore
):
    state = await _issue_state(kv)
    response = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    session_cookie = next(
        c
        for c in response.headers.get_list("set-cookie")
        if c.startswith(settings.session_cookie_name)
    )
    assert "Secure" not in session_cookie


async def test_callback_sets_secure_cookies_when_configured_for_https(
    client: AsyncClient,
    github_app_mode,
    fake_oauth,
    kv: InMemoryKVStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "cookie_secure", True)
    state = await _issue_state(kv)
    response = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    session_cookie = next(
        c
        for c in response.headers.get_list("set-cookie")
        if c.startswith(settings.session_cookie_name)
    )
    assert "Secure" in session_cookie


async def test_callback_rejects_a_forged_state(
    client: AsyncClient, github_app_mode, fake_oauth
):
    response = await client.get(
        "/api/v1/auth/github/callback?code=abc&state=forged",
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "invalid or has expired" in response.json()["detail"]
    # The code must never be exchanged when state validation fails.
    assert fake_oauth.exchanged_codes == []


async def test_callback_rejects_a_replayed_state(
    client: AsyncClient, github_app_mode, fake_oauth, kv: InMemoryKVStore
):
    state = await _issue_state(kv)
    first = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert first.status_code == 303

    client.cookies.clear()
    replay = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert replay.status_code == 422


async def test_callback_without_state_is_rejected(
    client: AsyncClient, github_app_mode, fake_oauth
):
    response = await client.get(
        "/api/v1/auth/github/callback?code=abc", follow_redirects=False
    )
    assert response.status_code == 422


async def test_callback_without_code_is_rejected(
    client: AsyncClient, github_app_mode, fake_oauth, kv: InMemoryKVStore
):
    state = await _issue_state(kv)
    response = await client.get(
        f"/api/v1/auth/github/callback?state={state}", follow_redirects=False
    )
    assert response.status_code == 422
    assert "authorization code" in response.json()["detail"]


async def test_callback_surfaces_a_github_denial(
    client: AsyncClient, github_app_mode, fake_oauth
):
    response = await client.get(
        "/api/v1/auth/github/callback?error=access_denied",
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "access_denied" in response.json()["detail"]


async def test_callback_maps_an_oauth_exchange_failure(
    client: AsyncClient, github_app_mode, fake_oauth, kv: InMemoryKVStore
):
    fake_oauth.exchange_error = OAuthError("The code has expired.")
    state = await _issue_state(kv)
    response = await client.get(
        f"/api/v1/auth/github/callback?code=stale&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "The code has expired" in response.json()["detail"]


async def test_callback_returning_user_is_not_duplicated(
    client: AsyncClient,
    github_app_mode,
    fake_oauth,
    kv: InMemoryKVStore,
    session: AsyncSession,
):
    from sqlalchemy import func, select

    for _ in range(2):
        client.cookies.clear()
        state = await _issue_state(kv)
        await client.get(
            f"/api/v1/auth/github/callback?code=abc&state={state}",
            follow_redirects=False,
        )

    count = (
        await session.execute(
            select(func.count()).select_from(User).where(User.github_user_id == 4242)
        )
    ).scalar_one()
    assert count == 1


async def test_oauth_token_is_never_persisted_anywhere(
    client: AsyncClient,
    github_app_mode,
    fake_oauth,
    kv: InMemoryKVStore,
    session: AsyncSession,
):
    """Identity-only: the OAuth token must not reach Redis, the session, or
    the users table."""
    state = await _issue_state(kv)
    await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )

    assert "gho_never_persist_me" not in kv.raw_values()

    from app.services.user_service import UserService

    user = await UserService(session).get_by_github_user_id(4242)
    assert "gho_never_persist_me" not in str(user.__dict__)


# -- logout -----------------------------------------------------------------


async def test_logout_destroys_the_session(
    signed_in: tuple[AsyncClient, User], github_app_mode, kv: InMemoryKVStore
):
    client, _ = signed_in
    session_id = client.cookies[settings.session_cookie_name]

    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 204

    from app.services.session_store import SessionStore

    assert await SessionStore(kv, ttl_seconds=60).get(session_id) is None


async def test_logout_clears_both_cookies(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    client, _ = signed_in
    response = await client.post("/api/v1/auth/logout")
    cleared = " ".join(response.headers.get_list("set-cookie"))
    assert settings.session_cookie_name in cleared
    assert settings.csrf_cookie_name in cleared


async def test_logout_without_a_session_is_idempotent(
    client: AsyncClient, github_app_mode
):
    assert (await client.post("/api/v1/auth/logout")).status_code == 204


async def test_session_no_longer_works_after_logout(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    client, _ = signed_in
    await client.post("/api/v1/auth/logout")
    client.cookies.set(settings.session_cookie_name, "stale")
    assert (await client.get("/api/v1/projects")).status_code == 401


# -- CSRF -------------------------------------------------------------------


async def test_cookie_authenticated_write_requires_a_csrf_token(
    signed_in: tuple[AsyncClient, User], github_app_mode, project
):
    client, _ = signed_in
    del client.headers[CSRF_HEADER]
    response = await client.post(
        "/api/v1/tasks",
        json={"project_id": project.id, "title": "T", "request": "r"},
    )
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


async def test_cookie_authenticated_write_rejects_a_wrong_csrf_token(
    signed_in: tuple[AsyncClient, User], github_app_mode, project
):
    client, _ = signed_in
    client.headers[CSRF_HEADER] = "wrong-token"
    response = await client.post(
        "/api/v1/tasks",
        json={"project_id": project.id, "title": "T", "request": "r"},
    )
    assert response.status_code == 403


async def test_cookie_authenticated_write_succeeds_with_the_right_token(
    signed_in: tuple[AsyncClient, User],
    github_app_mode,
    session: AsyncSession,
):
    client, user = signed_in
    # The project must belong to the signed-in user — since Phase 6C a task
    # cannot be created against someone else's project.
    from app.models import Project

    owned = Project(
        user_id=user.id, name="Theirs", description="", repo_path="sample_repo"
    )
    session.add(owned)
    await session.commit()
    await session.refresh(owned)

    response = await client.post(
        "/api/v1/tasks",
        json={"project_id": owned.id, "title": "T", "request": "r"},
    )
    assert response.status_code == 201


async def test_csrf_does_not_apply_to_safe_methods(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    client, _ = signed_in
    del client.headers[CSRF_HEADER]
    assert (await client.get("/api/v1/projects")).status_code == 200


# -- rate limiting ----------------------------------------------------------


async def test_login_is_rate_limited(
    client: AsyncClient, github_app_mode, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "auth_rate_limit_requests", 3)
    for _ in range(3):
        response = await client.get(
            "/api/v1/auth/github/login", follow_redirects=False
        )
        assert response.status_code == 307
    blocked = await client.get("/api/v1/auth/github/login", follow_redirects=False)
    assert blocked.status_code == 429


async def test_callback_is_rate_limited(
    client: AsyncClient, github_app_mode, fake_oauth, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "auth_rate_limit_requests", 2)
    for _ in range(2):
        await client.get(
            "/api/v1/auth/github/callback?state=x", follow_redirects=False
        )
    blocked = await client.get(
        "/api/v1/auth/github/callback?state=x", follow_redirects=False
    )
    assert blocked.status_code == 429


# -- open routes ------------------------------------------------------------


async def test_health_and_config_stay_open_in_github_app_mode(
    client: AsyncClient, github_app_mode
):
    assert (await client.get("/health")).status_code == 200
    config = await client.get("/api/v1/config")
    assert config.status_code == 200
    assert config.json()["auth_mode"] == "github_app"
