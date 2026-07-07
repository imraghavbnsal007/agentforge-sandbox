import shutil
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import RunStatus, TaskStatus
from app.models import AgentRun, FileChange, Project, Task
from app.services.publisher import (
    GitHubPublisher,
    PublishError,
    PublishService,
    branch_name_for,
    validate_github_project,
)
from tests.test_services.test_run_service import FakeExecutor


class FakeGit:
    """Stands in for GitClient; 'clone' copies the sample repo."""

    def __init__(self) -> None:
        self.pushed: list[str] = []
        self.applied: list[str] = []

    async def clone(self, repo_url: str, dest: Path, branch: str) -> None:
        shutil.copytree(settings.sample_repo_path, dest, dirs_exist_ok=True)

    async def create_branch(self, cwd: Path, name: str) -> None:
        self.branch = name

    async def apply_diff(self, cwd: Path, diff: str) -> None:
        self.applied.append(diff)

    async def commit_all(self, cwd: Path, message: str) -> str:
        return "a" * 40

    async def push(self, cwd: Path, repo_url: str, branch: str) -> None:
        self.pushed.append(branch)


class FakeAPI:
    async def create_pull_request(self, owner, repo, head, base, title, body) -> str:
        self.created = {"owner": owner, "repo": repo, "head": head, "base": base}
        return f"https://github.com/{owner}/{repo}/pull/1"


async def _make_github_task(session: AsyncSession, status: TaskStatus) -> Task:
    project = Project(
        name="GitHub Project",
        repo_path="",
        repo_url="https://github.com/acme/widget.git",
        default_branch="main",
        github_owner="acme",
        github_repo="widget",
    )
    session.add(project)
    await session.flush()
    task = Task(
        project_id=project.id,
        title="Add divide function!",
        request="Add divide.",
        status=status,
    )
    session.add(task)
    await session.flush()
    run = AgentRun(
        task_id=task.id,
        mode="mock",
        status=RunStatus.completed,
        summary="## Summary",
        file_changes=[
            FileChange(path="calculator.py", change_type="modify", diff="--- a/x\n")
        ],
        test_results=[],
    )
    session.add(run)
    await session.commit()
    return task


def test_branch_name_slug():
    task = Task(id=7, title="Add divide function!", request="r", project_id=1)
    task.id = 7
    assert branch_name_for(task) == "agentforge/task-7-add-divide-function"


def test_validate_requires_config_and_token(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "tok")
    incomplete = Project(name="p", repo_url=None, github_owner="a", github_repo=None)
    with pytest.raises(PublishError, match="not GitHub-configured"):
        validate_github_project(incomplete)

    complete = Project(
        name="p",
        repo_url="https://github.com/a/b.git",
        github_owner="a",
        github_repo="b",
    )
    monkeypatch.setattr(settings, "github_token", "")
    with pytest.raises(PublishError, match="GITHUB_TOKEN is not set"):
        validate_github_project(complete)


def test_validate_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "tok")
    monkeypatch.setattr(settings, "github_allowed_repos", "acme/widget, acme/other")
    ok = Project(
        name="p",
        repo_url="https://github.com/acme/widget.git",
        github_owner="acme",
        github_repo="widget",
    )
    validate_github_project(ok)  # should not raise

    rogue = Project(
        name="p2",
        repo_url="https://github.com/evil/repo.git",
        github_owner="evil",
        github_repo="repo",
    )
    with pytest.raises(PublishError, match="not in GITHUB_ALLOWED_REPOS"):
        validate_github_project(rogue)


async def test_publish_service_happy_path(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_token", "tok")
    monkeypatch.setattr(settings, "github_allowed_repos", "")
    task = await _make_github_task(session, TaskStatus.publishing)

    git, api = FakeGit(), FakeAPI()
    publisher = GitHubPublisher(git=git, api=api, executor=FakeExecutor())
    await PublishService(session, publisher=publisher).publish_task(task.id)

    assert task.status == TaskStatus.completed
    run = task.runs[-1]
    assert run.branch_name == "agentforge/task-%d-add-divide-function" % task.id
    assert run.commit_sha == "a" * 40
    assert run.pr_url.endswith("/pull/1")
    assert git.pushed == [run.branch_name]
    assert api.created["base"] == "main"
    assert "pull request opened" in run.log


async def test_publish_failure_returns_to_review(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_token", "tok")
    task = await _make_github_task(session, TaskStatus.publishing)

    # Fresh-clone verification tests fail -> publish refused.
    publisher = GitHubPublisher(
        git=FakeGit(), api=FakeAPI(), executor=FakeExecutor(passed=1, failed=2)
    )
    await PublishService(session, publisher=publisher).publish_task(task.id)

    assert task.status == TaskStatus.ready_for_review
    run = task.runs[-1]
    assert "no longer pass tests" in run.error
    assert run.pr_url is None


async def test_publish_skipped_unless_publishing(session: AsyncSession):
    task = await _make_github_task(session, TaskStatus.ready_for_review)
    await PublishService(session, publisher=GitHubPublisher(FakeGit(), FakeAPI())).publish_task(task.id)
    assert task.status == TaskStatus.ready_for_review  # untouched
