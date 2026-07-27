"""Minting and caching of GitHub App installation access tokens.

Guarantees:

  * tokens live in Redis only — never in PostgreSQL, never in a response body;
  * a cached token is handed out only while it has more than the refresh
    margin left, so a long clone or push cannot straddle expiry;
  * cache entries are scoped: a token narrowed to two repositories is never
    reused for a request wanting a different set;
  * nothing here logs a token, and every error message is scrubbed.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.services.github_app_api import (
    GitHubAppAPI,
    GitHubAppAPIError,
    InstallationToken,
)
from app.services.github_app_auth import generate_app_jwt

logger = logging.getLogger(__name__)

TOKEN_KEY_PREFIX = "agentforge:installation_token:"
SCOPE_ALL = "all"


def _scope_key(repository_ids: list[int] | None) -> str:
    if not repository_ids:
        return SCOPE_ALL
    # Order-independent, collision-resistant, and short enough to read in
    # a Redis key listing.
    joined = ",".join(str(i) for i in sorted(set(repository_ids)))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def _cache_key(github_installation_id: int, repository_ids: list[int] | None) -> str:
    return (
        f"{TOKEN_KEY_PREFIX}{github_installation_id}:"
        f"{_scope_key(repository_ids)}"
    )


class GitHubAppTokenService:
    def __init__(
        self,
        kv,
        api: GitHubAppAPI | None = None,
        refresh_margin_seconds: int | None = None,
    ) -> None:
        self._kv = kv
        self._api = api or GitHubAppAPI()
        self._margin = (
            refresh_margin_seconds
            if refresh_margin_seconds is not None
            else settings.installation_token_refresh_margin_seconds
        )

    async def get_installation_token(
        self,
        github_installation_id: int,
        repository_ids: list[int] | None = None,
    ) -> InstallationToken:
        """Return a usable installation token, from cache or freshly minted.

        `repository_ids` narrows the token to those repositories only —
        least privilege for the operation at hand.
        """
        key = _cache_key(github_installation_id, repository_ids)

        cached = await self._read_cached(key)
        if cached is not None:
            return cached

        app_jwt = generate_app_jwt()
        token = await self._api.create_installation_token(
            app_jwt, github_installation_id, repository_ids
        )
        await self._write_cached(key, token)
        logger.info(
            "Minted installation token for installation %s (scope=%s, "
            "expires in %.0fs)",
            github_installation_id,
            _scope_key(repository_ids),
            token.seconds_remaining(),
        )
        return token

    async def invalidate(
        self,
        github_installation_id: int,
        repository_ids: list[int] | None = None,
    ) -> None:
        """Drop a cached token — used when GitHub reports the installation
        suspended or removed."""
        await self._kv.delete(_cache_key(github_installation_id, repository_ids))

    async def _read_cached(self, key: str) -> InstallationToken | None:
        raw = await self._kv.get(key)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            expires_at = datetime.fromisoformat(payload["expires_at"])
            token = InstallationToken(
                token=payload["token"],
                expires_at=expires_at,
                permissions=payload.get("permissions") or {},
                repository_selection=payload.get("repository_selection") or "",
            )
        except (ValueError, KeyError, TypeError):
            await self._kv.delete(key)
            return None

        # Independent of the Redis TTL: a token inside the refresh margin is
        # treated as already gone, so callers never start work on one that
        # will expire mid-operation.
        if token.seconds_remaining() <= self._margin:
            await self._kv.delete(key)
            return None
        return token

    async def _write_cached(self, key: str, token: InstallationToken) -> None:
        ttl = int(token.seconds_remaining() - self._margin)
        if ttl <= 0:
            # Already inside the margin — usable right now, not worth caching.
            return
        await self._kv.set(
            key,
            json.dumps(
                {
                    "token": token.token,
                    "expires_at": token.expires_at.astimezone(
                        timezone.utc
                    ).isoformat(),
                    "permissions": token.permissions,
                    "repository_selection": token.repository_selection,
                }
            ),
            ttl,
        )


__all__ = [
    "GitHubAppTokenService",
    "GitHubAppAPIError",
    "InstallationToken",
    "TOKEN_KEY_PREFIX",
]
