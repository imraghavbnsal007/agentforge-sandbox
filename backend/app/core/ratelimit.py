"""Fixed-window rate limiting for the sign-in routes.

Deliberately simple: one counter per (scope, client, window). A fixed window
can allow up to 2x the limit across a boundary, which is an acceptable
trade for brute-force protection on auth endpoints and avoids the extra
state a sliding window needs.
"""

import time

from app.core.exceptions import RateLimitedError

RATE_LIMIT_KEY_PREFIX = "agentforge:ratelimit:"


class RateLimiter:
    def __init__(self, kv, limit: int, window_seconds: int) -> None:
        self._kv = kv
        self._limit = limit
        # A misconfigured zero/negative window would divide by zero when
        # bucketing; clamp rather than crash the request path.
        self._window = max(1, window_seconds)

    def _key(self, scope: str, identifier: str) -> str:
        window = int(time.time() // self._window)
        return f"{RATE_LIMIT_KEY_PREFIX}{scope}:{identifier}:{window}"

    async def check(self, scope: str, identifier: str) -> None:
        """Count this request; raise RateLimitedError once over the limit."""
        count = await self._kv.increment(self._key(scope, identifier), self._window)
        if count > self._limit:
            raise RateLimitedError(
                "Too many requests — wait a moment and try again."
            )
