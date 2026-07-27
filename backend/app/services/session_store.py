"""Server-side sessions.

The browser only ever holds an opaque random session id. Everything else —
which user it belongs to, the CSRF token — lives server-side in the KV store,
so logout and revocation take effect immediately rather than waiting for a
signed token to expire.

The GitHub OAuth access token is deliberately NOT part of a session. It is
used once during the callback to read the user's profile and then discarded;
repository access comes from GitHub App installation tokens, never from a
user's OAuth token.
"""

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

SESSION_KEY_PREFIX = "agentforge:session:"
USER_SESSIONS_KEY_PREFIX = "agentforge:user_sessions:"

SESSION_ID_BYTES = 32
CSRF_TOKEN_BYTES = 32


def _session_key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _user_sessions_key(user_id: int) -> str:
    return f"{USER_SESSIONS_KEY_PREFIX}{user_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionData:
    session_id: str
    user_id: int
    github_login: str
    csrf_token: str
    created_at: str
    last_seen_at: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "user_id": self.user_id,
                "github_login": self.github_login,
                "csrf_token": self.csrf_token,
                "created_at": self.created_at,
                "last_seen_at": self.last_seen_at,
            }
        )

    @classmethod
    def from_json(cls, session_id: str, raw: str) -> "SessionData | None":
        try:
            payload = json.loads(raw)
            return cls(
                session_id=session_id,
                user_id=int(payload["user_id"]),
                github_login=str(payload.get("github_login", "")),
                csrf_token=str(payload["csrf_token"]),
                created_at=str(payload.get("created_at", "")),
                last_seen_at=str(payload.get("last_seen_at", "")),
            )
        except (ValueError, KeyError, TypeError):
            # A malformed record is treated as no session rather than an
            # error — the caller simply re-authenticates.
            return None


class SessionStore:
    def __init__(self, kv, ttl_seconds: int) -> None:
        self._kv = kv
        self._ttl = ttl_seconds

    async def create(self, user_id: int, github_login: str) -> SessionData:
        now = _now_iso()
        data = SessionData(
            session_id=secrets.token_urlsafe(SESSION_ID_BYTES),
            user_id=user_id,
            github_login=github_login,
            csrf_token=secrets.token_urlsafe(CSRF_TOKEN_BYTES),
            created_at=now,
            last_seen_at=now,
        )
        await self._kv.set(_session_key(data.session_id), data.to_json(), self._ttl)
        # Index by user so every session can be revoked at once when an
        # account is disabled or an installation is removed.
        await self._kv.set_add(
            _user_sessions_key(user_id), data.session_id, self._ttl
        )
        return data

    async def get(self, session_id: str) -> SessionData | None:
        if not session_id:
            return None
        raw = await self._kv.get(_session_key(session_id))
        if raw is None:
            return None
        return SessionData.from_json(session_id, raw)

    async def touch(self, data: SessionData) -> None:
        """Slide the expiry window on an active session."""
        data.last_seen_at = _now_iso()
        await self._kv.set(_session_key(data.session_id), data.to_json(), self._ttl)
        await self._kv.set_add(
            _user_sessions_key(data.user_id), data.session_id, self._ttl
        )

    async def delete(self, session_id: str) -> None:
        data = await self.get(session_id)
        await self._kv.delete(_session_key(session_id))
        if data is not None:
            await self._kv.set_remove(_user_sessions_key(data.user_id), session_id)

    async def revoke_all_for_user(self, user_id: int) -> int:
        """Invalidate every session belonging to a user. Returns how many."""
        key = _user_sessions_key(user_id)
        session_ids = await self._kv.set_members(key)
        for session_id in session_ids:
            await self._kv.delete(_session_key(session_id))
        await self._kv.delete(key)
        return len(session_ids)
