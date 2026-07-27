"""GitHub sign-in — user identity only.

Scope boundary, enforced by convention and asserted in tests: the access
token obtained here is used exactly once, to read the user's profile, and is
then dropped. It is never stored, never logged, and never used for Git
operations. Repository access comes from GitHub App installation tokens
(Phase 6B).
"""

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from app.core.config import settings

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

OAUTH_STATE_KEY_PREFIX = "agentforge:oauth_state:"
OAUTH_STATE_TTL_SECONDS = 600
STATE_BYTES = 32

REQUEST_TIMEOUT_SECONDS = 15


class OAuthError(Exception):
    """Sign-in failed. Messages are safe to show a user and never contain
    the authorization code or any token."""


@dataclass
class GitHubProfile:
    github_user_id: int
    github_login: str
    avatar_url: str | None
    display_name: str | None
    email: str | None


def _state_key(state: str) -> str:
    return f"{OAUTH_STATE_KEY_PREFIX}{state}"


@dataclass
class OAuthState:
    """What a validated state token carries back from the round trip."""

    redirect_to: str = "/"
    # Set when the round trip was started to verify a GitHub App
    # installation, so the callback knows to link it afterwards.
    installation_id: int | None = None


class OAuthStateStore:
    """Single-use, short-lived CSRF state for the OAuth round trip."""

    def __init__(self, kv) -> None:
        self._kv = kv

    async def issue(
        self, redirect_to: str = "/", installation_id: int | None = None
    ) -> str:
        state = secrets.token_urlsafe(STATE_BYTES)
        payload = json.dumps(
            {
                "redirect_to": redirect_to,
                "installation_id": installation_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        await self._kv.set(_state_key(state), payload, OAUTH_STATE_TTL_SECONDS)
        return state

    async def consume(self, state: str) -> OAuthState | None:
        """Validate and burn the state. Returns the carried values, or None
        when the state is unknown, already used, or expired."""
        if not state:
            return None
        raw = await self._kv.get_and_delete(_state_key(state))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except ValueError:
            return OAuthState()
        installation_id = payload.get("installation_id")
        return OAuthState(
            redirect_to=str(payload.get("redirect_to") or "/"),
            installation_id=int(installation_id) if installation_id else None,
        )


def authorize_url(state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.github_app_client_id,
            "redirect_uri": settings.github_app_callback_url,
            "state": state,
        }
    )
    return f"{GITHUB_AUTHORIZE_URL}?{query}"


class GitHubOAuthClient:
    """Talks to GitHub's OAuth endpoints. Injectable for tests."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _post(self, url: str, data: dict) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(
                url, data=data, headers={"Accept": "application/json"}
            )
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            return await client.post(
                url, data=data, headers={"Accept": "application/json"}
            )

    async def _get(self, url: str, token: str) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._client is not None:
            return await self._client.get(url, headers=headers)
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            return await client.get(url, headers=headers)

    async def exchange_code(self, code: str) -> str:
        """Trade the authorization code for a short-lived access token."""
        try:
            response = await self._post(
                GITHUB_TOKEN_URL,
                {
                    "client_id": settings.github_app_client_id,
                    "client_secret": settings.github_app_client_secret,
                    "code": code,
                    "redirect_uri": settings.github_app_callback_url,
                },
            )
        except httpx.HTTPError as exc:
            raise OAuthError(
                f"Could not reach GitHub to complete sign-in: {type(exc).__name__}"
            ) from exc

        if response.status_code != 200:
            raise OAuthError(
                f"GitHub rejected the sign-in request ({response.status_code})"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthError("GitHub returned an unreadable sign-in response") from exc

        # GitHub reports OAuth failures with HTTP 200 and an error body.
        if payload.get("error"):
            raise OAuthError(
                "GitHub sign-in failed: "
                f"{payload.get('error_description') or payload['error']}"
            )
        token = payload.get("access_token")
        if not token:
            raise OAuthError("GitHub did not return an access token")
        return str(token)

    async def fetch_profile(self, token: str) -> GitHubProfile:
        try:
            response = await self._get(GITHUB_USER_URL, token)
        except httpx.HTTPError as exc:
            raise OAuthError(
                f"Could not reach GitHub to read your profile: {type(exc).__name__}"
            ) from exc

        if response.status_code == 401:
            raise OAuthError("GitHub rejected the sign-in token (401)")
        if response.status_code != 200:
            raise OAuthError(
                f"GitHub profile lookup failed ({response.status_code})"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthError("GitHub returned an unreadable profile") from exc

        user_id = payload.get("id")
        login = payload.get("login")
        if not user_id or not login:
            raise OAuthError("GitHub profile is missing an id or login")
        return GitHubProfile(
            github_user_id=int(user_id),
            github_login=str(login),
            avatar_url=payload.get("avatar_url"),
            display_name=payload.get("name"),
            email=payload.get("email"),
        )
