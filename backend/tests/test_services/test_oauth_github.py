"""OAuth state handling and GitHub identity exchange.

No test here makes a live GitHub request — the httpx client is always a
scripted double.
"""

import httpx
import pytest

from app.core.config import settings
from app.services.kv_store import InMemoryKVStore
from app.services.oauth_github import (
    GitHubOAuthClient,
    OAuthError,
    OAuthStateStore,
    authorize_url,
)


@pytest.fixture(autouse=True)
def _oauth_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "github_app_client_id", "cid-123")
    monkeypatch.setattr(settings, "github_app_client_secret", "shhh-secret")
    monkeypatch.setattr(
        settings, "github_app_callback_url", "http://localhost:8000/cb"
    )


def _client(handler) -> GitHubOAuthClient:
    transport = httpx.MockTransport(handler)
    return GitHubOAuthClient(httpx.AsyncClient(transport=transport))


# -- authorize_url ----------------------------------------------------------


def test_authorize_url_carries_client_id_redirect_and_state():
    url = authorize_url("state-abc")
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=cid-123" in url
    assert "state=state-abc" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fcb" in url


def test_authorize_url_never_leaks_the_client_secret():
    assert "shhh-secret" not in authorize_url("s")


# -- OAuthStateStore --------------------------------------------------------


async def test_state_is_single_use(kv: InMemoryKVStore):
    store = OAuthStateStore(kv)
    state = await store.issue("/projects")
    assert await store.consume(state) == "/projects"
    # Second attempt (a replayed callback) finds nothing.
    assert await store.consume(state) is None


async def test_unknown_state_is_rejected(kv: InMemoryKVStore):
    assert await OAuthStateStore(kv).consume("forged") is None


async def test_empty_state_is_rejected(kv: InMemoryKVStore):
    assert await OAuthStateStore(kv).consume("") is None


async def test_state_defaults_to_root_redirect(kv: InMemoryKVStore):
    store = OAuthStateStore(kv)
    assert await store.consume(await store.issue()) == "/"


async def test_issued_states_are_unique(kv: InMemoryKVStore):
    store = OAuthStateStore(kv)
    assert await store.issue() != await store.issue()


# -- exchange_code ----------------------------------------------------------


async def test_exchange_code_returns_the_access_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/login/oauth/access_token"
        return httpx.Response(200, json={"access_token": "gho_secret", "type": "bearer"})

    assert await _client(handler).exchange_code("code-1") == "gho_secret"


async def test_exchange_code_maps_github_error_body():
    def handler(request: httpx.Request) -> httpx.Response:
        # GitHub reports OAuth failures with HTTP 200 and an error payload.
        return httpx.Response(
            200,
            json={
                "error": "bad_verification_code",
                "error_description": "The code has expired.",
            },
        )

    with pytest.raises(OAuthError, match="The code has expired"):
        await _client(handler).exchange_code("stale")


async def test_exchange_code_maps_http_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(OAuthError, match="500"):
        await _client(handler).exchange_code("code")


async def test_exchange_code_rejects_response_without_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"scope": ""})

    with pytest.raises(OAuthError, match="did not return an access token"):
        await _client(handler).exchange_code("code")


async def test_exchange_code_maps_network_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(OAuthError, match="Could not reach GitHub"):
        await _client(handler).exchange_code("code")


# -- fetch_profile ----------------------------------------------------------


async def test_fetch_profile_maps_all_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer gho_secret"
        return httpx.Response(
            200,
            json={
                "id": 583231,
                "login": "octocat",
                "avatar_url": "https://avatars.example/o.png",
                "name": "The Octocat",
                "email": "octocat@example.com",
            },
        )

    profile = await _client(handler).fetch_profile("gho_secret")

    assert profile.github_user_id == 583231
    assert profile.github_login == "octocat"
    assert profile.display_name == "The Octocat"
    assert profile.email == "octocat@example.com"


async def test_fetch_profile_tolerates_missing_optional_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 1, "login": "minimal"})

    profile = await _client(handler).fetch_profile("t")
    assert profile.display_name is None and profile.email is None


async def test_fetch_profile_rejects_unauthorized():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(OAuthError, match="401"):
        await _client(handler).fetch_profile("expired")


async def test_fetch_profile_rejects_payload_without_identity():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"login": "no-id"})

    with pytest.raises(OAuthError, match="missing an id or login"):
        await _client(handler).fetch_profile("t")
