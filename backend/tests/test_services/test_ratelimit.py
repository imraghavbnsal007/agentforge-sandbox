"""Fixed-window rate limiting."""

import pytest

from app.core.exceptions import RateLimitedError
from app.core.ratelimit import RateLimiter
from app.services.kv_store import InMemoryKVStore


async def test_requests_under_the_limit_pass(kv: InMemoryKVStore):
    limiter = RateLimiter(kv, limit=3, window_seconds=60)
    for _ in range(3):
        await limiter.check("login", "1.2.3.4")


async def test_request_over_the_limit_is_rejected(kv: InMemoryKVStore):
    limiter = RateLimiter(kv, limit=2, window_seconds=60)
    await limiter.check("login", "1.2.3.4")
    await limiter.check("login", "1.2.3.4")
    with pytest.raises(RateLimitedError, match="Too many requests"):
        await limiter.check("login", "1.2.3.4")


async def test_limits_are_per_client(kv: InMemoryKVStore):
    limiter = RateLimiter(kv, limit=1, window_seconds=60)
    await limiter.check("login", "1.1.1.1")
    # A different caller has its own budget.
    await limiter.check("login", "2.2.2.2")


async def test_limits_are_per_scope(kv: InMemoryKVStore):
    limiter = RateLimiter(kv, limit=1, window_seconds=60)
    await limiter.check("login", "1.1.1.1")
    await limiter.check("callback", "1.1.1.1")


async def test_budget_resets_in_the_next_window(
    kv: InMemoryKVStore, monkeypatch: pytest.MonkeyPatch
):
    limiter = RateLimiter(kv, limit=1, window_seconds=60)
    monkeypatch.setattr("app.core.ratelimit.time.time", lambda: 1_000.0)
    await limiter.check("login", "1.1.1.1")
    with pytest.raises(RateLimitedError):
        await limiter.check("login", "1.1.1.1")

    # Move into the next 60s bucket: the caller gets a fresh budget.
    monkeypatch.setattr("app.core.ratelimit.time.time", lambda: 1_100.0)
    await limiter.check("login", "1.1.1.1")


async def test_zero_window_is_clamped_rather_than_dividing_by_zero(
    kv: InMemoryKVStore,
):
    limiter = RateLimiter(kv, limit=1, window_seconds=0)
    await limiter.check("login", "1.1.1.1")  # must not raise ZeroDivisionError


async def test_increment_preserves_the_original_window(kv: InMemoryKVStore):
    """A busy client must not be able to extend its own window by making
    more requests."""
    await kv.increment("k", 60)
    first_expiry = kv._values["k"][1]
    await kv.increment("k", 60)
    assert kv._values["k"][1] == first_expiry
