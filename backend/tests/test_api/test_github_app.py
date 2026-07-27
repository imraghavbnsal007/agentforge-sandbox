"""GitHub App routes: installation listing, install redirect, setup callback,
and the sign-in callback's installation hand-off.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AuthMode
from app.models import GitHubInstallation, User, UserGitHubInstallation
from app.services.github_app_api import InstallationInfo
from app.services.kv_store import InMemoryKVStore
from app.services.oauth_github import GitHubProfile, OAuthStateStore


def _info(installation_id: int = 500, **overrides) -> InstallationInfo:
    base = {
        "github_installation_id": installation_id,
        "account_id": 4242,
        "account_login": "octocat",
        "account_type": "User",
        "target_type": "User",
        "repository_selection": "selected",
        "suspended_at": None,
        "permissions": {},
    }
    return InstallationInfo(**{**base, **overrides})


@pytest.fixture
def github_app_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_client_id", "cid")
    monkeypatch.setattr(settings, "github_app_client_secret", "secret")
    monkeypatch.setattr(settings, "github_app_name", "agentforge-dev")
    monkeypatch.setattr(settings, "github_app_id", "123456")
    monkeypatch.setattr(settings, "github_app_private_key_path", "/tmp/key.pem")


class FakeOAuthClient:
    """Sign-in double; also proves which token reached the linker."""

    profile = GitHubProfile(
        github_user_id=4242,
        github_login="octocat",
        avatar_url=None,
        display_name="The Octocat",
        email=None,
    )

    async def exchange_code(self, code: str) -> str:
        return "gho_transient_token"

    async def fetch_profile(self, token: str) -> GitHubProfile:
        return type(self).profile


class FakeAppAPI:
    """Stands in for GitHubAppAPI inside InstallationService."""

    user_installations: list[InstallationInfo] = []
    tokens_seen: list[str] = []

    async def list_user_installations(self, user_access_token: str):
        type(self).tokens_seen.append(user_access_token)
        return type(self).user_installations

    async def get_installation(self, app_jwt: str, github_installation_id: int):
        return next(
            i
            for i in type(self).user_installations
            if i.github_installation_id == github_installation_id
        )


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch):
    FakeAppAPI.user_installations = [_info()]
    FakeAppAPI.tokens_seen = []
    monkeypatch.setattr(
        "app.api.routes.auth._oauth_client_factory", FakeOAuthClient
    )
    monkeypatch.setattr(
        "app.services.installation_service.GitHubAppAPI", FakeAppAPI
    )
    monkeypatch.setattr(
        "app.services.installation_service.generate_app_jwt", lambda: "jwt"
    )
    return FakeAppAPI


# -- local mode backward compatibility -------------------------------------


async def test_installations_endpoint_works_in_local_mode(client: AsyncClient):
    """Local mode has no GitHub App, but the route must not 401 or crash —
    it reports an unconfigured, empty state."""
    response = await client.get("/api/v1/github/installations")
    assert response.status_code == 200
    body = response.json()
    assert body["installations"] == []
    assert body["app_configured"] is False


async def test_installations_endpoint_requires_auth_in_github_app_mode(
    client: AsyncClient, github_app_mode
):
    assert (await client.get("/api/v1/github/installations")).status_code == 401


# -- listing ----------------------------------------------------------------


async def test_listing_shows_only_the_callers_installations(
    signed_in: tuple[AsyncClient, User],
    session: AsyncSession,
    github_app_mode,
):
    client, user = signed_in

    mine = GitHubInstallation(
        github_installation_id=500, account_id=1, account_login="octocat"
    )
    theirs = GitHubInstallation(
        github_installation_id=600, account_id=2, account_login="acme"
    )
    session.add_all([mine, theirs])
    await session.commit()
    session.add(UserGitHubInstallation(user_id=user.id, installation_id=mine.id))
    await session.commit()

    body = (await client.get("/api/v1/github/installations")).json()
    logins = [i["account_login"] for i in body["installations"]]
    assert logins == ["octocat"]
    assert body["install_url"].endswith("/apps/agentforge-dev/installations/new")


async def test_listing_never_exposes_a_token_field(
    signed_in: tuple[AsyncClient, User], session: AsyncSession, github_app_mode
):
    client, user = signed_in
    installation = GitHubInstallation(
        github_installation_id=500, account_id=1, account_login="octocat"
    )
    session.add(installation)
    await session.commit()
    session.add(
        UserGitHubInstallation(user_id=user.id, installation_id=installation.id)
    )
    await session.commit()

    raw = (await client.get("/api/v1/github/installations")).text
    assert "token" not in raw.lower()


async def test_suspended_installation_is_reported_inactive(
    signed_in: tuple[AsyncClient, User], session: AsyncSession, github_app_mode
):
    from datetime import datetime, timezone

    client, user = signed_in
    installation = GitHubInstallation(
        github_installation_id=500,
        account_id=1,
        account_login="octocat",
        suspended_at=datetime.now(timezone.utc),
    )
    session.add(installation)
    await session.commit()
    session.add(
        UserGitHubInstallation(user_id=user.id, installation_id=installation.id)
    )
    await session.commit()

    body = (await client.get("/api/v1/github/installations")).json()
    assert body["installations"][0]["is_active"] is False
    assert body["installations"][0]["suspended_at"] is not None


# -- install redirect -------------------------------------------------------


async def test_install_redirects_to_the_apps_install_page(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    client, _ = signed_in
    response = await client.get("/api/v1/github/install", follow_redirects=False)
    assert response.status_code == 307
    assert (
        response.headers["location"]
        == "https://github.com/apps/agentforge-dev/installations/new"
    )


async def test_install_without_an_app_name_is_a_clear_error(
    signed_in: tuple[AsyncClient, User],
    github_app_mode,
    monkeypatch: pytest.MonkeyPatch,
):
    client, _ = signed_in
    monkeypatch.setattr(settings, "github_app_name", "")
    response = await client.get("/api/v1/github/install", follow_redirects=False)
    assert response.status_code == 422
    assert "GITHUB_APP_NAME" in response.json()["detail"]


# -- setup callback ---------------------------------------------------------


async def test_setup_bounces_through_authorize_to_obtain_proof(
    signed_in: tuple[AsyncClient, User], github_app_mode, kv: InMemoryKVStore
):
    """No token is stored to verify later — we redirect to get a fresh one."""
    client, _ = signed_in
    response = await client.get(
        "/api/v1/github/setup?installation_id=500&setup_action=install",
        follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"].startswith(
        "https://github.com/login/oauth/authorize?"
    )

    # The installation id rides in the single-use state, not in the browser.
    state_key = kv.keys_matching("agentforge:oauth_state:*")[0]
    assert '"installation_id": 500' in (await kv.get(state_key) or "")


async def test_setup_without_an_installation_id_just_returns_to_the_app(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    client, _ = signed_in
    response = await client.get("/api/v1/github/setup", follow_redirects=False)
    assert response.status_code == 303
    assert "/settings/installations" in response.headers["location"]


async def test_setup_marks_a_pending_org_approval(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    client, _ = signed_in
    response = await client.get(
        "/api/v1/github/setup?installation_id=500&setup_action=request",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "pending=1" in response.headers["location"]


async def test_setup_requires_authentication(
    client: AsyncClient, github_app_mode
):
    response = await client.get(
        "/api/v1/github/setup?installation_id=500", follow_redirects=False
    )
    assert response.status_code == 401


# -- sign-in callback links the installation --------------------------------


async def test_callback_links_the_installation_from_githubs_query(
    client: AsyncClient,
    github_app_mode,
    fake_github,
    kv: InMemoryKVStore,
    session: AsyncSession,
):
    state = await OAuthStateStore(kv).issue("/")
    response = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}"
        "&installation_id=500&setup_action=install",
        follow_redirects=False,
    )
    assert response.status_code == 303

    from sqlalchemy import select

    installation = (
        await session.execute(
            select(GitHubInstallation).where(
                GitHubInstallation.github_installation_id == 500
            )
        )
    ).scalar_one_or_none()
    assert installation is not None


async def test_callback_links_the_installation_carried_in_state(
    client: AsyncClient,
    github_app_mode,
    fake_github,
    kv: InMemoryKVStore,
    session: AsyncSession,
):
    """The setup-URL path: the id came from our own state, not the query."""
    state = await OAuthStateStore(kv).issue(
        "/settings/installations", installation_id=500
    )
    response = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 303

    from sqlalchemy import select

    count = (
        await session.execute(select(GitHubInstallation))
    ).scalars().all()
    assert len(count) == 1


async def test_callback_uses_the_fresh_oauth_token_for_verification(
    client: AsyncClient, github_app_mode, fake_github, kv: InMemoryKVStore
):
    state = await OAuthStateStore(kv).issue("/", installation_id=500)
    await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    # Exactly one use, and it is the token from this exchange.
    assert fake_github.tokens_seen == ["gho_transient_token"]


async def test_callback_never_persists_the_oauth_token(
    client: AsyncClient,
    github_app_mode,
    fake_github,
    kv: InMemoryKVStore,
):
    state = await OAuthStateStore(kv).issue("/", installation_id=500)
    await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "gho_transient_token" not in kv.raw_values()


async def test_forged_installation_id_signs_in_but_does_not_link(
    client: AsyncClient,
    github_app_mode,
    fake_github,
    kv: InMemoryKVStore,
    session: AsyncSession,
):
    """A user claiming an installation that is not theirs still gets a
    session — but no link, and a redirect that explains why."""
    fake_github.user_installations = [_info(500)]
    state = await OAuthStateStore(kv).issue("/")
    response = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}"
        "&installation_id=999",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "error=not_available" in response.headers["location"]

    from sqlalchemy import func, select

    links = (
        await session.execute(
            select(func.count()).select_from(UserGitHubInstallation)
        )
    ).scalar_one()
    assert links == 0


async def test_sign_in_without_an_installation_is_unaffected(
    client: AsyncClient, github_app_mode, fake_github, kv: InMemoryKVStore
):
    """Phase 6A's plain sign-in path must behave exactly as before."""
    state = await OAuthStateStore(kv).issue("/projects")
    response = await client.get(
        f"/api/v1/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:3000/projects"
    assert fake_github.tokens_seen == []


# -- sync -------------------------------------------------------------------


async def test_sync_refuses_an_installation_the_user_does_not_have(
    signed_in: tuple[AsyncClient, User], github_app_mode, session: AsyncSession
):
    client, _ = signed_in
    installation = GitHubInstallation(
        github_installation_id=500, account_id=1, account_login="someoneelse"
    )
    session.add(installation)
    await session.commit()

    response = await client.post("/api/v1/github/installations/500/sync")
    assert response.status_code == 404


async def test_sync_of_an_unknown_installation_is_404(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    client, _ = signed_in
    assert (
        await client.post("/api/v1/github/installations/777/sync")
    ).status_code == 404
