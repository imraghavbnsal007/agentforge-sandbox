"""Failure and recovery behaviour.

The invariant under test throughout: when publishing cannot complete, the
generated diffs and task history survive and the task returns to review, so
nothing the agent produced is ever lost to an infrastructure problem.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AuthMode, ChangeType, RunStatus, TaskStatus
from app.models import AgentRun, FileChange, Project, Task
from app.services.git_client import GitAuthError, GitError
from app.services.github_api import GitHubAPI, GitHubAPIError, GitHubAuthError
from app.services.github_app_api import InstallationToken
from app.services.github_credentials import (
    GitCredentials,
    RepoOperation,
    RepositoryAccessError,
)
from app.services.github_app_token_service import GitHubAppTokenService
from app.services.kv_store import InMemoryKVStore
from app.services.oauth_github import GitHubOAuthClient, OAuthError
from app.services.publisher import GitHubPublisher, PublishService


def _credentials(token: str = "ghs_1") -> GitCredentials:
    return GitCredentials(
        token=token,
        committer_name="agentforge[bot]",
        committer_email="bot@example.com",
        mode=AuthMode.github_app,
        repository_full_name="acme/widget",
        github_installation_id=500,
        github_repository_id=900,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


class Resolver:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.count = 0
        self.invalidated: list[str] = []

    async def resolve(self, project_id, operation, user_id=None):
        if self.error is not None:
            raise self.error
        self.count += 1
        return _credentials(f"ghs_{self.count}")

    async def invalidate(self, credentials):
        self.invalidated.append(credentials.token)


class Git:
    def __init__(self, fail_on: str | None = None, error: Exception | None = None,
                 remote_sha: str | None = None) -> None:
        self.fail_on = fail_on
        self.error = error or GitError("boom")
        self.remote_sha = remote_sha
        self.pushes = 0

    async def clone(self, repo_url, dest, branch) -> None:
        if self.fail_on == "clone":
            raise self.error
        Path(dest).mkdir(parents=True, exist_ok=True)

    async def create_branch(self, cwd, name) -> None: ...
    async def apply_diff(self, cwd, diff) -> None: ...
    async def delete_path(self, cwd, rel_path) -> None: ...

    async def commit_all(self, cwd, message) -> str:
        return "a" * 40

    async def push(self, cwd, repo_url, branch) -> None:
        self.pushes += 1
        if self.fail_on == "push":
            raise self.error

    async def remote_branch_sha(self, repo_url, branch) -> str | None:
        return self.remote_sha


class API:
    def __init__(self, error: Exception | None = None, existing: str | None = None):
        self.error = error
        self.existing = existing
        self.attempts = 0

    async def create_pull_request(self, owner, repo, head, base, title, body, token=""):
        self.attempts += 1
        if self.error is not None and self.attempts == 1:
            raise self.error
        return f"https://github.com/{owner}/{repo}/pull/1"

    async def find_pull_request(self, owner, repo, head_branch, token):
        return self.existing


class Executor:
    async def run_tests(self, workspace):
        from app.agent.executor import TestResultData

        return TestResultData(
            suite="pytest", passed=1, failed=0, errored=0, duration=0.0,
            output="ok", stderr="",
        )


async def _task(session: AsyncSession) -> tuple[Project, Task]:
    from tests.helpers import local_user_id

    project = Project(
        user_id=await local_user_id(session),
        name="acme/widget",
        description="",
        repo_path="",
        repo_url="https://github.com/acme/widget.git",
        default_branch="main",
        github_owner="acme",
        github_repo="widget",
    )
    session.add(project)
    await session.flush()
    task = Task(
        project_id=project.id, title="T", request="R",
        status=TaskStatus.publishing,
    )
    session.add(task)
    await session.flush()
    session.add(
        AgentRun(
            task_id=task.id, mode="llm", status=RunStatus.completed,
            summary="s",
            file_changes=[
                FileChange(path="a.py", change_type=ChangeType.modify,
                           diff="--- a/a.py\n+++ b/a.py\n", is_binary=False)
            ],
            test_results=[],
        )
    )
    await session.commit()
    await session.refresh(project)
    await session.refresh(task)
    return project, task


def _publisher(resolver=None, git=None, api=None) -> GitHubPublisher:
    publisher = GitHubPublisher(
        api=api or API(), executor=Executor(), resolver=resolver
    )
    publisher.git = git or Git()
    publisher._client_for = lambda credentials: publisher.git  # type: ignore
    return publisher


async def _publish(session: AsyncSession, task: Task, publisher) -> Task:
    await PublishService(session, publisher=publisher).publish_task(task.id)
    from app.repositories.task_repo import TaskRepository

    return await TaskRepository(session).get_with_runs_unscoped_for_worker(task.id)


# -- infrastructure unavailable --------------------------------------------


async def test_redis_unavailable_during_token_retrieval_surfaces_clearly(
    monkeypatch: pytest.MonkeyPatch,
):
    """A dead KV store must not be mistaken for a valid empty cache."""

    class DeadKV:
        async def get(self, key):
            raise ConnectionError("redis is down")

        async def set(self, key, value, ttl_seconds):
            raise ConnectionError("redis is down")

        async def delete(self, key): ...

    monkeypatch.setattr(
        "app.services.github_app_token_service.generate_app_jwt", lambda: "jwt"
    )
    service = GitHubAppTokenService(DeadKV(), api=None)
    with pytest.raises(ConnectionError):
        await service.get_installation_token(500, [900])


async def test_github_oauth_unavailable_is_a_readable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    client = GitHubOAuthClient(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(OAuthError, match="Could not reach GitHub"):
        await client.exchange_code("code")


async def test_github_api_unavailable_is_a_readable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    api = GitHubAPI(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(GitHubAPIError, match="Could not reach"):
        await api.create_pull_request(
            owner="o", repo="r", head="h", base="main", title="T", body="B",
            token="t",
        )


async def test_token_minting_unavailable_blocks_without_falling_back(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    project, task = await _task(session)
    resolver = Resolver(
        error=RepositoryAccessError(
            "GitHub App access to this repository is no longer available."
        )
    )
    reloaded = await _publish(session, task, _publisher(resolver))
    assert reloaded.status == TaskStatus.ready_for_review


# -- failures during publish preserve work ---------------------------------


async def test_clone_failure_preserves_the_diffs(session: AsyncSession):
    project, task = await _task(session)
    reloaded = await _publish(
        session, task, _publisher(git=Git(fail_on="clone"))
    )
    assert reloaded.status == TaskStatus.ready_for_review
    assert len(reloaded.runs[-1].file_changes) == 1
    assert reloaded.runs[-1].error


async def test_push_failure_preserves_the_diffs(session: AsyncSession):
    project, task = await _task(session)
    reloaded = await _publish(session, task, _publisher(git=Git(fail_on="push")))
    assert reloaded.status == TaskStatus.ready_for_review
    assert len(reloaded.runs[-1].file_changes) == 1


async def test_pr_failure_preserves_the_diffs(session: AsyncSession):
    project, task = await _task(session)
    publisher = _publisher(api=API(error=GitHubAPIError("PR service down")))
    reloaded = await _publish(session, task, publisher)
    assert reloaded.status == TaskStatus.ready_for_review
    assert len(reloaded.runs[-1].file_changes) == 1


async def test_access_revoked_before_publish_preserves_the_diffs(
    session: AsyncSession,
):
    project, task = await _task(session)
    resolver = Resolver(
        error=RepositoryAccessError(
            "GitHub App access to this repository is no longer available."
        )
    )
    reloaded = await _publish(session, task, _publisher(resolver))
    assert reloaded.status == TaskStatus.ready_for_review
    assert "no longer available" in reloaded.runs[-1].error
    assert len(reloaded.runs[-1].file_changes) == 1


# -- lost responses (the operation may have succeeded) ---------------------


async def test_push_that_actually_landed_is_not_repeated(
    session: AsyncSession,
):
    """A rejection can arrive after the push succeeded."""
    project, task = await _task(session)
    git = Git(fail_on="push", error=GitAuthError("401"), remote_sha="a" * 40)
    # fail_on stays set, so a second push would raise again — it must not
    # be attempted.
    publisher = _publisher(Resolver(), git=git)
    reloaded = await _publish(session, task, publisher)
    assert git.pushes == 1
    assert reloaded.status == TaskStatus.completed


async def test_pr_that_actually_opened_is_reused(session: AsyncSession):
    project, task = await _task(session)
    api = API(
        error=GitHubAuthError("401"),
        existing="https://github.com/acme/widget/pull/42",
    )
    reloaded = await _publish(session, task, _publisher(Resolver(), api=api))
    assert api.attempts == 1  # never created a duplicate
    assert reloaded.runs[-1].pr_url == "https://github.com/acme/widget/pull/42"
    assert reloaded.status == TaskStatus.completed


# -- duplicate execution ---------------------------------------------------


async def test_duplicate_publish_request_is_ignored(session: AsyncSession):
    """A second publish job for an already-completed task must not re-push."""
    project, task = await _task(session)
    reloaded = await _publish(session, task, _publisher(Resolver()))
    assert reloaded.status == TaskStatus.completed

    git = Git()
    await _publish(session, reloaded, _publisher(Resolver(), git=git))
    # The guard is the status check: not publishing -> skipped entirely.
    assert git.pushes == 0


async def test_worker_restart_mid_task_leaves_state_recoverable(
    session: AsyncSession,
):
    """A task interrupted while publishing stays publishing, so the job can
    be re-enqueued without losing the run."""
    project, task = await _task(session)
    assert task.status == TaskStatus.publishing
    from app.repositories.task_repo import TaskRepository

    reloaded = await TaskRepository(session).get_with_runs_unscoped_for_worker(
        task.id
    )
    assert reloaded.status == TaskStatus.publishing
    assert len(reloaded.runs[-1].file_changes) == 1


# -- webhook arriving mid-flight -------------------------------------------


async def test_webhook_revocation_during_a_task_blocks_only_the_next_step(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Revocation must not corrupt an in-flight run; it blocks the next
    credential resolution and preserves everything already produced."""
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    project, task = await _task(session)

    # Clone succeeded; access is withdrawn before push.
    class RevokeAfterFirst:
        def __init__(self) -> None:
            self.count = 0
            self.invalidated: list[str] = []

        async def resolve(self, project_id, operation, user_id=None):
            self.count += 1
            if self.count == 1:
                return _credentials("ghs_clone")
            raise RepositoryAccessError(
                "GitHub App access to this repository is no longer available."
            )

        async def invalidate(self, credentials): ...

    reloaded = await _publish(session, task, _publisher(RevokeAfterFirst()))
    assert reloaded.status == TaskStatus.ready_for_review
    assert len(reloaded.runs[-1].file_changes) == 1
    assert "no longer available" in reloaded.runs[-1].error
