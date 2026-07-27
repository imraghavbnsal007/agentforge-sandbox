"""Small async key/value interface backing sessions, OAuth state, and rate limits.

Two implementations: Redis for real deployments, in-memory for tests. Keeping
the surface this narrow means the session store never depends on Redis
directly, so every consumer is testable without a server.

Values are opaque strings; callers serialize. Set-typed keys exist only to
support "revoke every session for this user".
"""

import fnmatch
import json
import time
from typing import Protocol


class KVStore(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def get_and_delete(self, key: str) -> str | None:
        """Atomic read-then-delete — the primitive that makes single-use
        OAuth state single-use even under concurrent callbacks."""
        ...

    async def set_add(self, key: str, member: str, ttl_seconds: int) -> None: ...

    async def set_members(self, key: str) -> list[str]: ...

    async def set_remove(self, key: str, member: str) -> None: ...

    async def increment(self, key: str, ttl_seconds: int) -> int:
        """Increment a counter, setting the TTL on first write. Returns the
        new value."""
        ...


class InMemoryKVStore:
    """Test/local double. Expiry is evaluated lazily on read."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float]] = {}
        self._sets: dict[str, tuple[set[str], float]] = {}

    def _live(self, expires_at: float) -> bool:
        return expires_at > time.monotonic()

    async def get(self, key: str) -> str | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if not self._live(expires_at):
            self._values.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._values[key] = (value, time.monotonic() + ttl_seconds)

    async def delete(self, key: str) -> None:
        self._values.pop(key, None)

    async def get_and_delete(self, key: str) -> str | None:
        value = await self.get(key)
        self._values.pop(key, None)
        return value

    async def set_add(self, key: str, member: str, ttl_seconds: int) -> None:
        members, _ = self._sets.get(key, (set(), 0.0))
        members.add(member)
        self._sets[key] = (members, time.monotonic() + ttl_seconds)

    async def set_members(self, key: str) -> list[str]:
        entry = self._sets.get(key)
        if entry is None:
            return []
        members, expires_at = entry
        if not self._live(expires_at):
            self._sets.pop(key, None)
            return []
        return sorted(members)

    async def set_remove(self, key: str, member: str) -> None:
        entry = self._sets.get(key)
        if entry is not None:
            entry[0].discard(member)

    async def increment(self, key: str, ttl_seconds: int) -> int:
        current = await self.get(key)
        value = int(current) + 1 if current is not None else 1
        # Preserve the original window: only the first write sets the expiry.
        if current is None:
            await self.set(key, str(value), ttl_seconds)
        else:
            _, expires_at = self._values[key]
            self._values[key] = (str(value), expires_at)
        return value

    # -- Test helpers (not part of the protocol) ---------------------------

    def keys_matching(self, pattern: str) -> list[str]:
        return sorted(k for k in self._values if fnmatch.fnmatch(k, pattern))

    def raw_values(self) -> str:
        """Everything stored, as one string — used by tests asserting that a
        secret never reached the store."""
        return json.dumps(
            {
                "values": {k: v for k, (v, _) in self._values.items()},
                "sets": {k: sorted(m) for k, (m, _) in self._sets.items()},
            }
        )


class RedisKVStore:
    """Redis-backed store. Decodes to str at the boundary so callers never
    deal with bytes."""

    def __init__(self, client) -> None:
        self._client = client

    @staticmethod
    def _decode(value) -> str | None:
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def get(self, key: str) -> str | None:
        return self._decode(await self._client.get(key))

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def get_and_delete(self, key: str) -> str | None:
        # GETDEL (Redis 6.2+) keeps this atomic; a pipeline fallback would
        # still race two concurrent callbacks against the same state token.
        return self._decode(await self._client.getdel(key))

    async def set_add(self, key: str, member: str, ttl_seconds: int) -> None:
        pipe = self._client.pipeline()
        pipe.sadd(key, member)
        pipe.expire(key, ttl_seconds)
        await pipe.execute()

    async def set_members(self, key: str) -> list[str]:
        members = await self._client.smembers(key)
        return sorted(self._decode(m) or "" for m in members)

    async def set_remove(self, key: str, member: str) -> None:
        await self._client.srem(key, member)

    async def increment(self, key: str, ttl_seconds: int) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds, nx=True)  # only the first write sets it
        result = await pipe.execute()
        return int(result[0])
