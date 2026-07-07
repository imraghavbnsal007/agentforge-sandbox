"""Thin GitHub REST API client for opening pull requests."""

import httpx

GITHUB_API = "https://api.github.com"


class GitHubAPIError(Exception):
    pass


class GitHubAPI:
    def __init__(self, token: str) -> None:
        self._token = token

    async def create_pull_request(
        self, owner: str, repo: str, head: str, base: str, title: str, body: str
    ) -> str:
        """Open a PR and return its html_url."""
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.post(
                    f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={"title": title, "head": head, "base": base, "body": body},
                )
            except httpx.HTTPError as exc:
                raise GitHubAPIError(
                    f"Could not reach the GitHub API: {type(exc).__name__}"
                ) from exc

        if response.status_code == 201:
            return response.json()["html_url"]
        if response.status_code == 401:
            raise GitHubAPIError("GitHub authentication failed (401) — check GITHUB_TOKEN")
        if response.status_code in (403, 404):
            raise GitHubAPIError(
                f"GitHub repo {owner}/{repo} not found or token lacks access "
                f"({response.status_code}) — the token needs Contents and "
                "Pull requests read/write permissions"
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
