"""Publisher credential lifecycle: per-operation resolution, revalidation,
and safe retry of the two non-idempotent operations.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ChangeType, RunStatus, TaskStatus
from app.models import AgentRun, FileChange, Project, Task
from app.services.git_client import GitAuthError
from app.services.github_api import GitHubAuthError
from app.services.github_credentials import (
    GitCredentials,
    RepoOperation,
    RepositoryAccessError,
)
from app.services.publisher import GitHubPublisher, PublishService
from app.core.enums import AuthMode


def _credentials(token: str = "ghs_1") -> GitCredentials:
    return GitCredentials(
        token=token,
        committer_name="AgentForge[bot]",
        committer_email="bot@agentforge.example",
        mode=AuthMode.github_app,
        repository_full_name="acme/widget",
        github_installation_id=500,
        github_repository_id=900,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


class FakeResolver:
    """Records every resolution so per-operation scoping is provable."""

    def __init__(self, tokens: list[str] | None = None, error: Exception | None = None):
        self.tokens = tokens or ["ghs_1", "ghs_2", "ghs_3", "ghs_4"]
        self.error = error
        self.operations: list[RepoOperation] = []
        self.invalidated: list[str] = []

    async def resolve(self, project_id, operation, user_id=None):
        if self.error is not None:
            raise self.error
        self.operations.append(operation)
        index = min(len(self.operations) - 1, len(self.tokens) - 1)
        return _credentials(self.tokens[index])

    async def invalidate(self, credentials):
        self.invalidated.append(credentials.token)


class FakeGit:
    def __init__(self, push_failures: int = 0, remote_sha: str | None = None):
        self.push_failures = push_failures
        self.remote_sha = remote_sha
        self.pushes = 0
        self.pushed: list[str] = []

    async def clone(self, repo_url, dest, branch) -> None:
        Path(dest).mkdir(parents=True, exist_ok=True)

    async def create_branch(self, cwd, name) -> None: ...
    async def apply_diff(self, cwd, diff) -> None: ...
    async def delete_path(self, cwd, rel_path) -> None: ...

    async def commit_all(self, cwd, message) -> str:
        return "a" * 40

    async def push(self, cwd, repo_url, branch) -> None:
        self.pushes += 1
        if self.pushes <= self.push_failures:
            raise GitAuthError("git push failed: Authentication failed")
        self.pushed.append(branch)

    async def remote_branch_sha(self, repo_url, branch) -> str | None:
        return self.remote_sha


class FakeAPI:
    def __init__(self, pr_failures: int = 0, existing: str | None = None):
        self.pr_failures = pr_failures
        self.existing = existing
        self.attempts = 0
        self.tokens_used: list[str] = []
        self.lookups = 0

    async def create_pull_request(self, owner, repo, head, base, title, body, token=""):
        self.attempts += 1
        self.tokens_used.append(token)
        if self.attempts <= self.pr_failures:
            raise GitHubAuthError("GitHub rejected the credential (401)")
        return f"https://github.com/{owner}/{repo}/pull/1"

    async def find_pull_request(self, owner, repo, head_branch, token):
        self.lookups += 1
        return self.existing


class FakeExecutor:
    async def run_tests(self, workspace):
        from app.agent.executor import TestResultData

        return TestResultData(
            suite="pytest", passed=1, failed=0, errored=0, duration=0.1,
            output="ok", stderr="",
        )


async def _github_task(session: AsyncSession) -> tuple[Project, Task, AgentRun]:
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
    task = Task(project_id=project.id, title="Add thing", request="R",
                status=TaskStatus.publishing)
    session.add(task)
    await session.flush()
    run = AgentRun(
        task_id=task.id, mode="llm", status=RunStatus.completed,
        summary="Summary",
        file_changes=[
            FileChange(path="a.py", change_type=ChangeType.modify,
                       diff="--- a/a.py\n+++ b/a.py\n", is_binary=False)
        ],
        test_results=[],
    )
    session.add(run)
    await session.commit()
    await session.refresh(project)
    await session.refresh(task)
    # Re-fetch with the collection eagerly loaded: the publisher iterates
    # run.file_changes, and a lazy load inside the async session raises.
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    run = (
        await session.execute(
            select(AgentRun)
            .where(AgentRun.id == run.id)
            .options(selectinload(AgentRun.file_changes))
        )
    ).scalar_one()
    return project, task, run


def _publisher(resolver, git=None, api=None) -> GitHubPublisher:
    publisher = GitHubPublisher(api=api or FakeAPI(), executor=FakeExecutor(),
                                resolver=resolver)
    # Substitute the git layer without marking it "injected", so the publisher
    # still builds a client per resolved credential.
    publisher.git = git or FakeGit()
    publisher._client_for = lambda credentials: publisher.git  # type: ignore[method-assign]
    return publisher


def _log(_message: str) -> None: ...


# -- per-operation resolution ----------------------------------------------


async def test_credentials_are_resolved_once_per_operation(
    session: AsyncSession,
):
    """Clone, push and PR each get their own resolution — nothing is held
    for the duration of the run."""
    project, task, run = await _github_task(session)
    resolver = FakeResolver()
    await _publisher(resolver).publish(project, task, run, _log)

    assert resolver.operations == [
        RepoOperation.clone,
        RepoOperation.push,
        RepoOperation.pull_request,
    ]


async def test_pull_request_uses_the_freshly_resolved_token(
    session: AsyncSession,
):
    project, task, run = await _github_task(session)
    api = FakeAPI()
    await _publisher(FakeResolver(), api=api).publish(project, task, run, _log)
    # Third resolution -> third token.
    assert api.tokens_used == ["ghs_3"]


async def test_access_lost_before_clone_aborts_publishing(
    session: AsyncSession,
):
    project, task, run = await _github_task(session)
    resolver = FakeResolver(error=RepositoryAccessError("access gone"))
    with pytest.raises(RepositoryAccessError):
        await _publisher(resolver).publish(project, task, run, _log)


# -- push retry (non-idempotent) -------------------------------------------


async def test_rejected_push_revalidates_and_retries_once(
    session: AsyncSession,
):
    project, task, run = await _github_task(session)
    resolver = FakeResolver()
    git = FakeGit(push_failures=1, remote_sha=None)

    await _publisher(resolver, git=git).publish(project, task, run, _log)

    # Token invalidated, access revalidated, push retried exactly once.
    assert resolver.invalidated == ["ghs_2"]
    assert git.pushes == 2
    assert resolver.operations.count(RepoOperation.push) == 2


async def test_push_is_not_repeated_when_the_first_attempt_landed(
    session: AsyncSession,
):
    """A rejection can arrive after the push succeeded — check the remote
    before retrying a non-idempotent operation."""
    project, task, run = await _github_task(session)
    git = FakeGit(push_failures=1, remote_sha="a" * 40)

    await _publisher(FakeResolver(), git=git).publish(project, task, run, _log)

    assert git.pushes == 1  # never retried
    assert git.pushed == []


async def test_push_rejection_without_a_resolver_propagates(
    session: AsyncSession,
):
    """Local mode has no resolver, so there is nothing to revalidate."""
    project, task, run = await _github_task(session)
    publisher = GitHubPublisher(
        git=FakeGit(push_failures=1), api=FakeAPI(), executor=FakeExecutor()
    )
    with pytest.raises(GitAuthError):
        await publisher.publish(project, task, run, _log)


# -- PR retry (non-idempotent) ---------------------------------------------


async def test_rejected_pr_revalidates_and_retries_once(
    session: AsyncSession,
):
    project, task, run = await _github_task(session)
    resolver = FakeResolver()
    api = FakeAPI(pr_failures=1, existing=None)

    await _publisher(resolver, api=api).publish(project, task, run, _log)

    assert resolver.invalidated == ["ghs_3"]
    assert api.lookups == 1  # checked before retrying
    assert api.attempts == 2


async def test_existing_pr_is_reused_instead_of_opening_a_duplicate(
    session: AsyncSession,
):
    """If the first attempt actually opened the PR, return it."""
    project, task, run = await _github_task(session)
    api = FakeAPI(pr_failures=1, existing="https://github.com/acme/widget/pull/9")

    result = await _publisher(FakeResolver(), api=api).publish(
        project, task, run, _log
    )

    assert result.pr_url == "https://github.com/acme/widget/pull/9"
    assert api.attempts == 1  # never created a second one


async def test_retry_happens_at_most_once(session: AsyncSession):
    project, task, run = await _github_task(session)
    api = FakeAPI(pr_failures=2)  # fails again on retry
    with pytest.raises(GitHubAuthError):
        await _publisher(FakeResolver(), api=api).publish(project, task, run, _log)
    assert api.attempts == 2


# -- blocked publishing preserves history ----------------------------------


async def test_blocked_publish_preserves_the_run_and_returns_to_review(
    session: AsyncSession,
):
    """Access withdrawn between approval and publish must not lose work."""
    project, task, run = await _github_task(session)
    publisher = _publisher(
        FakeResolver(
            error=RepositoryAccessError(
                "GitHub App access to this repository is no longer available."
            )
        )
    )
    await PublishService(session, publisher=publisher).publish_task(task.id)

    from app.repositories.task_repo import TaskRepository

    reloaded = await TaskRepository(session).get_with_runs_unscoped_for_worker(
        task.id
    )
    assert reloaded.status == TaskStatus.ready_for_review
    assert "no longer available" in reloaded.runs[-1].error
    # The generated diffs survive.
    assert len(reloaded.runs[-1].file_changes) == 1
