"""Publishing emits a live event trail on the same stream as execution.

The security property asserted throughout: no token, no authenticated URL and
no raw GitHub response reaches an event.
"""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ChangeType,
    ErrorCode,
    RunStatus,
    TaskEventType,
    TaskStatus,
)
from app.models import AgentRun, FileChange, Project, Task
from app.services.github_credentials import RepositoryAccessError
from app.services.kv_store import InMemoryKVStore
from app.services.publisher import GitHubPublisher, PublishService
from app.services.task_events import TaskEventService

TOKEN = "ghs_installation_token_never_in_an_event"


class Git:
    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail

    async def clone(self, repo_url, dest, branch) -> None:
        from pathlib import Path

        if self.fail == "clone":
            from app.services.git_client import GitError

            raise GitError(f"boom using {TOKEN}")
        Path(dest).mkdir(parents=True, exist_ok=True)

    async def create_branch(self, cwd, name) -> None: ...
    async def apply_diff(self, cwd, diff) -> None: ...
    async def delete_path(self, cwd, rel) -> None: ...

    async def commit_all(self, cwd, message) -> str:
        return "a" * 40

    async def push(self, cwd, repo_url, branch) -> None: ...

    async def remote_branch_sha(self, repo_url, branch) -> str | None:
        return None


class API:
    async def create_pull_request(self, owner, repo, head, base, title, body, token=""):
        return f"https://github.com/{owner}/{repo}/pull/1"

    async def find_pull_request(self, owner, repo, head_branch, token):
        return None


class Executor:
    async def run_tests(self, workspace):
        from app.agent.executor import TestResultData

        return TestResultData(
            suite="pytest", passed=1, failed=0, errored=0, duration=0.0,
            output="ok", stderr="",
        )


@pytest.fixture
async def publishable(session: AsyncSession) -> tuple[Project, Task, AgentRun]:
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
        project_id=project.id, title="Add thing", request="R",
        status=TaskStatus.publishing,
    )
    session.add(task)
    await session.flush()
    run = AgentRun(
        task_id=task.id, mode="llm", status=RunStatus.completed, summary="s",
        file_changes=[
            FileChange(path="a.py", change_type=ChangeType.modify,
                       diff="--- a\n+++ b\n", is_binary=False)
        ],
        test_results=[],
    )
    session.add(run)
    await session.commit()
    await session.refresh(project)
    await session.refresh(task)
    return project, task, run


def _publisher(git=None, api=None) -> GitHubPublisher:
    publisher = GitHubPublisher(api=api or API(), executor=Executor())
    publisher.git = git or Git()
    publisher._client_for = lambda credentials: publisher.git  # type: ignore
    return publisher


async def _publish(session, task, publisher, kv) -> list:
    events = TaskEventService(session, kv)
    await PublishService(session, publisher=publisher, events=events).publish_task(
        task.id
    )
    return await events.history(task.id)


# -- the event trail --------------------------------------------------------


async def test_publishing_emits_a_full_lifecycle(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    _, task, _ = publishable
    history = await _publish(session, task, _publisher(), kv)
    types = [str(e.event_type) for e in history]

    assert TaskEventType.publish_started in types
    assert TaskEventType.branch_pushed in types
    assert TaskEventType.pr_created in types


async def test_events_cover_credential_validation_and_clone(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    _, task, _ = publishable
    history = await _publish(session, task, _publisher(), kv)
    messages = " | ".join(e.message or "" for e in history)

    assert "Repository access verified" in messages
    assert "Cloning repository" in messages
    assert "Repository cloned" in messages


async def test_push_and_pr_events_carry_safe_context(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    _, task, _ = publishable
    history = await _publish(session, task, _publisher(), kv)

    pushed = next(
        e for e in history if str(e.event_type) == TaskEventType.branch_pushed
    )
    assert pushed.safe_metadata["branch"].startswith("agentforge/task-")
    assert pushed.safe_metadata["commit_sha"] == "a" * 40

    created = next(
        e for e in history if str(e.event_type) == TaskEventType.pr_created
    )
    assert created.safe_metadata["pr_url"].startswith("https://github.com/")


async def test_events_are_published_to_the_task_channel_for_sse(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    """This is what makes publishing visible on the existing SSE stream."""
    from app.services.task_events import channel_for

    _, task, _ = publishable
    await _publish(session, task, _publisher(), kv)
    assert len(kv.published[channel_for(task.id)]) > 0


async def test_sequence_numbers_continue_from_the_run(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    """Publishing shares the run's tracker, so ordering is uninterrupted."""
    _, task, run = publishable
    events = TaskEventService(session, kv)
    await events.emit(task, TaskEventType.run_started, run=run, user_id=1)

    history = await _publish(session, task, _publisher(), kv)
    numbers = [e.sequence_number for e in history]
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)


# -- failure ----------------------------------------------------------------


async def test_a_failed_publish_emits_publish_failed(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    _, task, _ = publishable
    history = await _publish(session, task, _publisher(git=Git(fail="clone")), kv)

    failure = next(
        e for e in history if str(e.event_type) == TaskEventType.publish_failed
    )
    assert failure.error_code is not None


async def test_a_blocked_publish_reports_lost_access(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    class Resolver:
        async def resolve(self, project_id, operation, user_id=None):
            raise RepositoryAccessError("access gone")

        async def invalidate(self, credentials): ...

    _, task, _ = publishable
    publisher = _publisher()
    publisher.resolver = Resolver()

    history = await _publish(session, task, publisher, kv)
    failure = next(
        e for e in history if str(e.event_type) == TaskEventType.publish_failed
    )
    assert failure.error_code == ErrorCode.repository_access_lost


# -- secret hygiene ---------------------------------------------------------


async def test_no_token_reaches_any_publish_event(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    _, task, _ = publishable
    history = await _publish(session, task, _publisher(git=Git(fail="clone")), kv)

    serialised = json.dumps(
        [
            {"m": e.message, "meta": e.safe_metadata, "code": e.error_code}
            for e in history
        ]
    )
    assert TOKEN not in serialised
    assert TOKEN not in json.dumps(kv.published)


async def test_failure_messages_come_from_the_catalogue_not_the_exception(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    """A raw message can carry a path, a command, or an upstream response."""
    _, task, _ = publishable
    history = await _publish(session, task, _publisher(git=Git(fail="clone")), kv)

    failure = next(
        e for e in history if str(e.event_type) == TaskEventType.publish_failed
    )
    assert "boom" not in (failure.message or "")


async def test_no_authenticated_url_appears_in_events(
    session: AsyncSession, publishable, kv: InMemoryKVStore
):
    _, task, _ = publishable
    history = await _publish(session, task, _publisher(), kv)
    serialised = json.dumps([e.safe_metadata for e in history])
    assert "x-access-token" not in serialised
    assert "extraheader" not in serialised
