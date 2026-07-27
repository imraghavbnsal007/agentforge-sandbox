"""GitHub App REST calls: installation records, installation tokens, and the
user's own installation list.

Every response that could carry a token is scrubbed before it reaches an
exception message — see `redact_secrets`.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 20

# GitHub credential shapes. ghs_ is an installation token, ghu_/gho_ a user
# token, and a JWT is three base64url segments.
_SECRET_PATTERNS = [
    re.compile(r"gh[susopr]_[A-Za-z0-9_]{8,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
]


def redact_secrets(text: str) -> str:
    """Replace anything token-shaped. Applied to every message that could
    quote a response body or a header."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


class GitHubAppAPIError(Exception):
    """A GitHub App API call failed. Messages are always scrubbed."""

    def __init__(self, message: str) -> None:
        super().__init__(redact_secrets(message))


class InstallationNotFoundError(GitHubAppAPIError):
    """The installation does not exist, or this App cannot see it."""


@dataclass
class InstallationInfo:
    """GitHub's canonical record of an installation."""

    github_installation_id: int
    account_id: int
    account_login: str
    account_type: str
    target_type: str
    repository_selection: str
    suspended_at: datetime | None = None
    permissions: dict = field(default_factory=dict)


@dataclass
class InstallationToken:
    """A short-lived installation access token. Never persisted to Postgres,
    never returned to the frontend."""

    token: str
    expires_at: datetime
    permissions: dict = field(default_factory=dict)
    repository_selection: str = ""

    def seconds_remaining(self, now: datetime | None = None) -> float:
        moment = now or datetime.now(timezone.utc)
        return (self.expires_at - moment).total_seconds()

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # Guarantees a stray repr() in a log or traceback cannot leak it.
        return f"InstallationToken(expires_at={self.expires_at.isoformat()})"


def _parse_timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_installation(payload: dict) -> InstallationInfo:
    account = payload.get("account") or {}
    return InstallationInfo(
        github_installation_id=int(payload["id"]),
        account_id=int(account.get("id") or 0),
        account_login=str(account.get("login") or ""),
        account_type=str(account.get("type") or "User"),
        target_type=str(payload.get("target_type") or account.get("type") or "User"),
        repository_selection=str(payload.get("repository_selection") or "selected"),
        suspended_at=_parse_timestamp(payload.get("suspended_at")),
        permissions=payload.get("permissions") or {},
    )


class GitHubAppAPI:
    """HTTP surface for app-level GitHub endpoints. Injectable for tests."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _request(
        self, method: str, url: str, token: str, json_body: dict | None = None
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            if self._client is not None:
                return await self._client.request(
                    method, url, headers=headers, json=json_body
                )
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                return await client.request(
                    method, url, headers=headers, json=json_body
                )
        except httpx.HTTPError as exc:
            raise GitHubAppAPIError(
                f"Could not reach the GitHub API: {type(exc).__name__}"
            ) from exc

    async def get_installation(
        self, app_jwt: str, github_installation_id: int
    ) -> InstallationInfo:
        """Read an installation record using the App JWT."""
        response = await self._request(
            "GET",
            f"{GITHUB_API}/app/installations/{github_installation_id}",
            app_jwt,
        )
        if response.status_code == 404:
            raise InstallationNotFoundError(
                f"Installation {github_installation_id} does not exist or is "
                "not visible to this GitHub App."
            )
        if response.status_code == 401:
            raise GitHubAppAPIError(
                "GitHub rejected the App JWT (401) — check GITHUB_APP_ID and "
                "the private key."
            )
        if response.status_code != 200:
            raise GitHubAppAPIError(
                f"GitHub installation lookup failed ({response.status_code})"
            )
        return parse_installation(response.json())

    async def create_installation_token(
        self,
        app_jwt: str,
        github_installation_id: int,
        repository_ids: list[int] | None = None,
    ) -> InstallationToken:
        """Exchange the App JWT for a scoped, short-lived installation token."""
        body: dict = {}
        if repository_ids:
            # Narrow the token to exactly the repositories needed.
            body["repository_ids"] = list(repository_ids)

        response = await self._request(
            "POST",
            f"{GITHUB_API}/app/installations/{github_installation_id}/access_tokens",
            app_jwt,
            json_body=body or None,
        )
        if response.status_code == 404:
            raise InstallationNotFoundError(
                f"Installation {github_installation_id} no longer exists — "
                "the GitHub App may have been uninstalled."
            )
        if response.status_code == 403:
            raise GitHubAppAPIError(
                f"Installation {github_installation_id} is suspended or "
                "forbidden (403)."
            )
        if response.status_code == 401:
            raise GitHubAppAPIError(
                "GitHub rejected the App JWT (401) — check GITHUB_APP_ID and "
                "the private key."
            )
        if response.status_code != 201:
            raise GitHubAppAPIError(
                f"Installation token request failed ({response.status_code})"
            )

        payload = response.json()
        token = payload.get("token")
        expires_at = _parse_timestamp(payload.get("expires_at"))
        if not token or expires_at is None:
            raise GitHubAppAPIError(
                "GitHub returned an installation token without a token or "
                "expiry."
            )
        return InstallationToken(
            token=str(token),
            expires_at=expires_at,
            permissions=payload.get("permissions") or {},
            repository_selection=str(payload.get("repository_selection") or ""),
        )

    async def list_user_installations(
        self, user_access_token: str
    ) -> list[InstallationInfo]:
        """Installations the *signed-in user* can access.

        This is the only call that uses a user OAuth token, and it is the
        authoritative check that a given installation really belongs to them.
        The token is passed in, used, and dropped by the caller — it is never
        stored.
        """
        response = await self._request(
            "GET",
            f"{GITHUB_API}/user/installations?per_page=100",
            user_access_token,
        )
        if response.status_code == 401:
            raise GitHubAppAPIError(
                "GitHub rejected the user token while listing installations "
                "(401)."
            )
        if response.status_code != 200:
            raise GitHubAppAPIError(
                f"Could not list your GitHub installations "
                f"({response.status_code})"
            )
        payload = response.json()
        return [
            parse_installation(item)
            for item in (payload.get("installations") or [])
        ]
