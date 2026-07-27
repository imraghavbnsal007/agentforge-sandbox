"""Server-side session lifecycle, expiry, and revocation."""

import json

import pytest

from app.services.kv_store import InMemoryKVStore
from app.services.session_store import (
    SESSION_KEY_PREFIX,
    SessionData,
    SessionStore,
)

TTL = 3600


@pytest.fixture
def store(kv: InMemoryKVStore) -> SessionStore:
    return SessionStore(kv, ttl_seconds=TTL)


async def test_create_then_get_roundtrip(store: SessionStore):
    created = await store.create(user_id=7, github_login="octocat")
    loaded = await store.get(created.session_id)
    assert loaded is not None
    assert loaded.user_id == 7
    assert loaded.github_login == "octocat"
    assert loaded.csrf_token == created.csrf_token


async def test_session_id_and_csrf_token_are_distinct_and_unguessable(
    store: SessionStore,
):
    a = await store.create(1, "a")
    b = await store.create(1, "b")
    assert a.session_id != b.session_id
    assert a.csrf_token != b.csrf_token
    assert a.session_id != a.csrf_token
    # token_urlsafe(32) -> 43 chars; anything much shorter is a bug.
    assert len(a.session_id) >= 40 and len(a.csrf_token) >= 40


async def test_unknown_session_returns_none(store: SessionStore):
    assert await store.get("nope") is None


async def test_empty_session_id_returns_none(store: SessionStore):
    assert await store.get("") is None


async def test_delete_removes_the_session(store: SessionStore):
    created = await store.create(3, "x")
    await store.delete(created.session_id)
    assert await store.get(created.session_id) is None


async def test_delete_is_idempotent(store: SessionStore):
    await store.delete("never-existed")  # must not raise


async def test_revoke_all_kills_every_session_for_that_user(store: SessionStore):
    first = await store.create(9, "u")
    second = await store.create(9, "u")
    other = await store.create(10, "other")

    revoked = await store.revoke_all_for_user(9)

    assert revoked == 2
    assert await store.get(first.session_id) is None
    assert await store.get(second.session_id) is None
    # A different user's session is untouched.
    assert await store.get(other.session_id) is not None


async def test_revoke_all_for_user_without_sessions_is_zero(store: SessionStore):
    assert await store.revoke_all_for_user(12345) == 0


async def test_expired_session_is_not_returned(kv: InMemoryKVStore):
    store = SessionStore(kv, ttl_seconds=0)
    created = await store.create(1, "u")
    assert await store.get(created.session_id) is None


async def test_touch_refreshes_last_seen(store: SessionStore):
    created = await store.create(2, "u")
    created.last_seen_at = "1999-01-01T00:00:00+00:00"
    await store.touch(created)
    loaded = await store.get(created.session_id)
    assert loaded is not None
    assert loaded.last_seen_at != "1999-01-01T00:00:00+00:00"


async def test_malformed_record_reads_as_no_session(
    store: SessionStore, kv: InMemoryKVStore
):
    await kv.set(f"{SESSION_KEY_PREFIX}broken", "not json", TTL)
    assert await store.get("broken") is None


async def test_record_missing_required_field_reads_as_no_session():
    assert SessionData.from_json("sid", json.dumps({"user_id": 1})) is None


async def test_session_never_stores_an_oauth_token(
    store: SessionStore, kv: InMemoryKVStore
):
    """The GitHub OAuth token is identity-only and must never be persisted."""
    await store.create(user_id=5, github_login="octocat")
    stored = kv.raw_values()
    assert "access_token" not in stored
    assert "gho_" not in stored
