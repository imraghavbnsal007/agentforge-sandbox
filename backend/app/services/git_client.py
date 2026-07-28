"""Subprocess git wrapper with token scrubbing.

Authentication is injected per-command via `-c http.<url>.extraheader` so the
token never appears in remote URLs, `.git/config`, or error output. As a
second layer, every captured output is scrubbed before it can reach a log or
exception message.
"""

import asyncio
import base64
import re
import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 120

DEFAULT_COMMITTER_NAME = "AgentForge"
DEFAULT_COMMITTER_EMAIL = "agentforge@localhost"

# git surfaces credential problems as prose on stderr. "Repository not found"
# is included deliberately: GitHub returns it for a private repo the caller
# may no longer access, rather than leaking existence with a 403.
_AUTH_FAILURE_PATTERNS = [
    re.compile(r"authentication failed", re.IGNORECASE),
    re.compile(r"invalid username or password", re.IGNORECASE),
    re.compile(r"could not read Username", re.IGNORECASE),
    re.compile(r"repository not found", re.IGNORECASE),
    re.compile(r"\b40[13]\b"),
    re.compile(r"permission.{0,20}denied", re.IGNORECASE),
]


class GitError(Exception):
    pass


class GitAuthError(GitError):
    """git refused the supplied credentials.

    Distinct so callers can invalidate a cached token, revalidate access and
    mint a fresh one — never so they can fall back to a different credential.
    """


def is_auth_failure(text: str) -> bool:
    return any(pattern.search(text) for pattern in _AUTH_FAILURE_PATTERNS)


class GitClient:
    """Runs git with credentials supplied per command.

    One instance wraps one set of credentials for one operation; callers
    construct a fresh client per resolved credential rather than holding a
    long-lived authenticated object.
    """

    def __init__(
        self,
        token: str = "",
        committer_name: str = DEFAULT_COMMITTER_NAME,
        committer_email: str = DEFAULT_COMMITTER_EMAIL,
    ) -> None:
        self._token = token
        self._committer_name = committer_name
        self._committer_email = committer_email
        self._b64 = (
            base64.b64encode(f"x-access-token:{token}".encode()).decode()
            if token
            else ""
        )

    def _scrub(self, text: str) -> str:
        for secret in (self._token, self._b64):
            if secret:
                text = text.replace(secret, "***")
        return text

    def _auth_args(self, repo_url: str) -> list[str]:
        if not self._token:
            return []
        return ["-c", f"http.{repo_url}.extraheader=AUTHORIZATION: basic {self._b64}"]

    async def _run(
        self, args: list[str], cwd: Path | None = None, stdin: str | None = None
    ) -> str:
        def call() -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", *args],
                cwd=cwd,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )

        try:
            proc = await asyncio.to_thread(call)
        except subprocess.TimeoutExpired:
            raise GitError(f"git {args[0]} timed out after {GIT_TIMEOUT_SECONDS}s")
        if proc.returncode != 0:
            detail = self._scrub((proc.stderr or proc.stdout).strip())
            if is_auth_failure(detail):
                raise GitAuthError(f"git {args[0]} failed: {detail}")
            raise GitError(f"git {args[0]} failed: {detail}")
        return self._scrub(proc.stdout)

    async def ls_remote(self, repo_url: str, branch: str) -> None:
        """Verify the repo is reachable (auth ok) and the branch exists."""
        out = await self._run(
            [*self._auth_args(repo_url), "ls-remote", "--heads", repo_url, branch]
        )
        if not out.strip():
            raise GitError(
                f"Branch {branch!r} not found on the repository "
                "(repo reachable, but the branch does not exist)"
            )

    async def clone(self, repo_url: str, dest: Path, branch: str) -> None:
        await self._run(
            [
                *self._auth_args(repo_url),
                "clone",
                "--depth",
                "1",
                "--branch",
                branch,
                repo_url,
                str(dest),
            ]
        )
        # Commit identity for this clone only — never global, and never
        # written anywhere that outlives the workspace.
        await self._run(["config", "user.name", self._committer_name], cwd=dest)
        await self._run(["config", "user.email", self._committer_email], cwd=dest)

    async def create_branch(self, cwd: Path, name: str) -> None:
        await self._run(["checkout", "-b", name], cwd=cwd)

    async def apply_diff(self, cwd: Path, diff: str) -> None:
        if not diff.endswith("\n"):
            diff += "\n"
        await self._run(["apply", "--whitespace=nowarn"], cwd=cwd, stdin=diff)

    async def delete_path(self, cwd: Path, rel_path: str) -> None:
        await self._run(["rm", "-q", "--", rel_path], cwd=cwd)

    async def commit_all(self, cwd: Path, message: str) -> str:
        await self._run(["add", "-A"], cwd=cwd)
        await self._run(["commit", "-m", message], cwd=cwd)
        sha = await self._run(["rev-parse", "HEAD"], cwd=cwd)
        return sha.strip()

    async def push(self, cwd: Path, repo_url: str, branch: str) -> None:
        await self._run(
            [*self._auth_args(repo_url), "push", "origin", branch], cwd=cwd
        )

    async def remote_branch_sha(self, repo_url: str, branch: str) -> str | None:
        """The remote head of `branch`, or None when it does not exist.

        Used to decide whether a failed push actually landed: push is not
        idempotent, so it must never be blindly retried.
        """
        out = await self._run(
            [*self._auth_args(repo_url), "ls-remote", "--heads", repo_url, branch]
        )
        line = out.strip()
        return line.split()[0] if line else None
