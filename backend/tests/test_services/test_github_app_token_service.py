"""Installation-token minting, caching, scoping, and expiry-aware refresh."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services.github_app_api import (
    GitHubAppAPI,
    GitHubAppAPIError,
    InstallationNotFoundError,
    InstallationToken,
    redact_secrets,
)
from app.services.github_app_token_service import (
    TOKEN_KEY_PREFIX,
    GitHubAppTokenService,
)
from app.services.kv_store import InMemoryKVStore

MARGIN = 300


@pytest.fixture(autouse=True)
def _stub_app_jwt(monkeypatch: pytest.MonkeyPatch):
    """Signing is covered in test_github_app_auth; here it is a fixed value."""
    monkeypatch.setattr(
        "app.services.github_app_token_service.generate_app_jwt",
        lambda: "app.jwt.value",
    )


def _expiry(seconds_from_now: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
    ).isoformat()


class RecordingAPI(GitHubAppAPI):
    """Counts mints so cache hits are provable."""

    def __init__(self, expires_in: int = 3600) -> None:
        super().__init__()
        self.calls: list[tuple[int, list[int] | None]] = []
        self.expires_in = expires_in

    async def create_installation_token(
        self, app_jwt, github_installation_id, repository_ids=None
    ) -> InstallationToken:
        self.calls.append((github_installation_id, repository_ids))
        return InstallationToken(
            token=f"ghs_token_{len(self.calls)}",
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=self.expires_in),
            permissions={"contents": "write"},
            repository_selection="selected",
        )


def _service(kv, api, margin: int = MARGIN) -> GitHubAppTokenService:
    return GitHubAppTokenService(kv, api=api, refresh_margin_seconds=margin)


# -- minting and caching ----------------------------------------------------


async def test_mints_a_token_on_first_request(kv: InMemoryKVStore):
    api = RecordingAPI()
    token = await _service(kv, api).get_installation_token(42)
    assert token.token == "ghs_token_1"
    assert api.calls == [(42, None)]


async def test_second_request_is_served_from_cache(kv: InMemoryKVStore):
    api = RecordingAPI()
    service = _service(kv, api)
    first = await service.get_installation_token(42)
    second = await service.get_installation_token(42)
    assert first.token == second.token
    assert len(api.calls) == 1


async def test_different_installations_do_not_share_a_token(kv: InMemoryKVStore):
    api = RecordingAPI()
    service = _service(kv, api)
    a = await service.get_installation_token(1)
    b = await service.get_installation_token(2)
    assert a.token != b.token
    assert len(api.calls) == 2


async def test_narrowed_scope_gets_its_own_cache_entry(kv: InMemoryKVStore):
    """A token scoped to two repos must never be reused for a wider request."""
    api = RecordingAPI()
    service = _service(kv, api)
    await service.get_installation_token(7)
    await service.get_installation_token(7, repository_ids=[10, 20])
    assert len(api.calls) == 2
    assert api.calls[1] == (7, [10, 20])


async def test_scope_key_is_order_independent(kv: InMemoryKVStore):
    api = RecordingAPI()
    service = _service(kv, api)
    await service.get_installation_token(7, repository_ids=[20, 10])
    await service.get_installation_token(7, repository_ids=[10, 20])
    assert len(api.calls) == 1


async def test_repository_ids_are_forwarded_to_github(kv: InMemoryKVStore):
    api = RecordingAPI()
    await _service(kv, api).get_installation_token(9, repository_ids=[5])
    assert api.calls == [(9, [5])]


# -- expiry-aware refresh ---------------------------------------------------


async def test_token_inside_the_refresh_margin_is_reminted(kv: InMemoryKVStore):
    """A token with less than the margin left must not be handed out — a long
    push could otherwise straddle expiry."""
    api = RecordingAPI(expires_in=3600)
    service = _service(kv, api, margin=MARGIN)
    await service.get_installation_token(42)

    # Rewrite the cache entry as if it were nearly expired.
    key = f"{TOKEN_KEY_PREFIX}42:all"
    await kv.set(
        key,
        '{"token": "ghs_stale", "expires_at": "%s", "permissions": {}}'
        % _expiry(60),
        3600,
    )

    fresh = await service.get_installation_token(42)
    assert fresh.token != "ghs_stale"
    assert len(api.calls) == 2


async def test_token_outside_the_margin_is_reused(kv: InMemoryKVStore):
    api = RecordingAPI(expires_in=3600)
    service = _service(kv, api, margin=MARGIN)
    await service.get_installation_token(42)
    await service.get_installation_token(42)
    assert len(api.calls) == 1


async def test_token_already_inside_the_margin_is_not_cached(kv: InMemoryKVStore):
    api = RecordingAPI(expires_in=60)  # shorter than the 300s margin
    service = _service(kv, api, margin=MARGIN)
    token = await service.get_installation_token(42)
    assert token.token == "ghs_token_1"  # still returned, usable now
    assert kv.keys_matching(f"{TOKEN_KEY_PREFIX}*") == []


async def test_corrupt_cache_entry_is_discarded_and_reminted(kv: InMemoryKVStore):
    api = RecordingAPI()
    service = _service(kv, api)
    await kv.set(f"{TOKEN_KEY_PREFIX}42:all", "not json", 3600)
    token = await service.get_installation_token(42)
    assert token.token == "ghs_token_1"


async def test_invalidate_forces_a_remint(kv: InMemoryKVStore):
    api = RecordingAPI()
    service = _service(kv, api)
    await service.get_installation_token(42)
    await service.invalidate(42)
    await service.get_installation_token(42)
    assert len(api.calls) == 2


async def test_cached_token_lives_only_in_the_kv_store(kv: InMemoryKVStore):
    """Tokens are Redis-only; nothing here should imply a database write."""
    api = RecordingAPI()
    await _service(kv, api).get_installation_token(42)
    keys = kv.keys_matching(f"{TOKEN_KEY_PREFIX}*")
    assert keys == [f"{TOKEN_KEY_PREFIX}42:all"]


# -- token exchange over HTTP ----------------------------------------------


def _api(handler) -> GitHubAppAPI:
    return GitHubAppAPI(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_exchange_parses_token_and_expiry():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/app/installations/55/access_tokens"
        assert request.headers["Authorization"] == "Bearer app.jwt"
        return httpx.Response(
            201,
            json={
                "token": "ghs_abc123",
                "expires_at": _expiry(3600),
                "permissions": {"contents": "write"},
                "repository_selection": "selected",
            },
        )

    token = await _api(handler).create_installation_token("app.jwt", 55)
    assert token.token == "ghs_abc123"
    assert token.seconds_remaining() > 3000
    assert token.permissions == {"contents": "write"}


async def test_exchange_sends_repository_ids_when_scoped():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(
            201, json={"token": "ghs_x", "expires_at": _expiry(3600)}
        )

    await _api(handler).create_installation_token("j", 1, repository_ids=[3, 4])
    assert seen == {"repository_ids": [3, 4]}


async def test_exchange_maps_uninstalled_app_to_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    with pytest.raises(InstallationNotFoundError, match="no longer exists"):
        await _api(handler).create_installation_token("j", 1)


async def test_exchange_maps_suspension_to_a_readable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "suspended"})

    with pytest.raises(GitHubAppAPIError, match="suspended or"):
        await _api(handler).create_installation_token("j", 1)


async def test_exchange_maps_bad_jwt():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(GitHubAppAPIError, match="GITHUB_APP_ID"):
        await _api(handler).create_installation_token("j", 1)


async def test_exchange_rejects_a_response_without_expiry():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"token": "ghs_x"})

    with pytest.raises(GitHubAppAPIError, match="without a token or"):
        await _api(handler).create_installation_token("j", 1)


# -- secret redaction -------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "ghs_installationtoken1234",
        "ghu_usertoken1234567890",
        "gho_oauthtoken1234567890",
        "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiIxMjM0NTYifQ.c2lnbmF0dXJlaGVyZQ",
    ],
)
def test_redact_secrets_removes_token_shapes(secret):
    assert secret not in redact_secrets(f"failed with {secret} in body")
    assert "[REDACTED]" in redact_secrets(f"failed with {secret} in body")


def test_api_error_scrubs_tokens_in_its_message():
    error = GitHubAppAPIError("upstream said ghs_leakedtoken123456 was invalid")
    assert "ghs_leakedtoken123456" not in str(error)


def test_installation_token_repr_hides_the_token():
    """A stray repr in a traceback or log must not leak the value."""
    token = InstallationToken(
        token="ghs_supersecret", expires_at=datetime.now(timezone.utc)
    )
    assert "ghs_supersecret" not in repr(token)
