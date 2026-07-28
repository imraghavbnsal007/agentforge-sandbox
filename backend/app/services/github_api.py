"""Thin GitHub REST client for the pull-request workflow.

The token is supplied per call rather than held on the instance: credentials
are resolved immediately before each operation and discarded afterwards, so
there is no long-lived authenticated object to leak or go stale.
"""

import httpx

from app.services.github_app_api import redact_secrets

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS = 30


class GitHubAPIError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(redact_secrets(message))


class GitHubAuthError(GitHubAPIError):
    """GitHub rejected the credential (401/403).

    Distinct so callers can invalidate the cached token, revalidate access and
    mint a fresh one — never so they can fall back to a different credential.
    """


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


class GitHubAPI:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _request(
        self, method: str, url: str, token: str, json_body: dict | None = None
    ) -> httpx.Response:
        try:
            if self._client is not None:
                return await self._client.request(
                    method, url, headers=_headers(token), json=json_body
                )
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                return await client.request(
                    method, url, headers=_headers(token), json=json_body
                )
        except httpx.HTTPError as exc:
            raise GitHubAPIError(
                f"Could not reach the GitHub API: {type(exc).__name__}"
            ) from exc

    async def find_pull_request(
        self, owner: str, repo: str, head_branch: str, token: str
    ) -> str | None:
        """URL of an existing PR for `head_branch`, or None.

        Creating a pull request is not idempotent, so this is consulted before
        any retry: if the first attempt actually succeeded, we return that PR
        rather than opening a duplicate.
        """
        response = await self._request(
            "GET",
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
            f"?head={owner}:{head_branch}&state=all&per_page=1",
            token,
        )
        if response.status_code in (401, 403):
            raise GitHubAuthError(
                f"GitHub rejected the credential while checking for an "
                f"existing pull request ({response.status_code})"
            )
        if response.status_code != 200:
            return None
        try:
            items = response.json()
        except ValueError:
            return None
        if isinstance(items, list) and items:
            return items[0].get("html_url")
        return None

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
        token: str,
    ) -> str:
        """Open a PR and return its html_url."""
        response = await self._request(
            "POST",
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            token,
            json_body={"title": title, "head": head, "base": base, "body": body},
        )

        if response.status_code == 201:
            return response.json()["html_url"]
        if response.status_code in (401, 403):
            raise GitHubAuthError(
                f"GitHub rejected the credential when opening a pull request "
                f"({response.status_code}) — the installation may have lost "
                "access to this repository"
            )
        if response.status_code == 404:
            raise GitHubAuthError(
                f"GitHub repo {owner}/{repo} is not visible to this credential "
                "(404) — access may have been withdrawn"
            )
        detail = ""
        try:
            errors = response.json().get("errors") or []
            detail = "; ".join(
                e.get("message", "") for e in errors if isinstance(e, dict)
            )
        except Exception:
            pass
        raise GitHubAPIError(
            f"GitHub PR creation failed ({response.status_code})"
            + (f": {detail}" if detail else "")
        )
