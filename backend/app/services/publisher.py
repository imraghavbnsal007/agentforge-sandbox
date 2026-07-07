"""Turn an approved agent run into a GitHub pull request.

The run's workspace is long gone by approval time, so publishing works from
the stored diffs: fresh shallow clone of the default branch -> git apply each
diff -> re-run pytest as a final gate -> branch -> commit -> push -> open PR.
If the base branch moved in a way that conflicts with the diffs, git apply
fails loudly and the task stays ready_for_review with a readable error.
"""

import logging
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.executor import PytestExecutor, TestExecutor
from app.agent.runner import LogFn
from app.agent.workspace import Workspace
from app.core.config import settings
from app.core.enums import RunStatus, TaskStatus
from app.core.exceptions import NotFoundError
from app.models import AgentRun, Project, Task
from app.services.git_client import GitClient
from app.services.github_api import GitHubAPI

logger = logging.getLogger(__name__)


class PublishError(Exception):
    pass


@dataclass
class PublishResult:
    branch_name: str
    commit_sha: str
    pr_url: str


def branch_name_for(task: Task) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task.title.lower()).strip("-")[:40].rstrip("-")
    return f"agentforge/task-{task.id}-{slug or 'change'}"


def validate_github_project(project: Project) -> None:
    """Raises PublishError unless the project is fully and legally configured."""
    if not (project.repo_url and project.github_owner and project.github_repo):
        raise PublishError(
            f"Project {project.name!r} is not GitHub-configured "
            "(repo_url, github_owner and github_repo are all required)"
        )
    if not settings.github_token:
        raise PublishError(
            "GITHUB_TOKEN is not set — required to publish pull requests. "
            "Add it to .env and restart the backend and worker."
        )
    allowed = settings.allowed_repos()
    full_name = f"{project.github_owner}/{project.github_repo}"
    if allowed is not None and full_name not in allowed:
        raise PublishError(
            f"Repo {full_name} is not in GITHUB_ALLOWED_REPOS — publishing refused"
        )


class GitHubPublisher:
    def __init__(
        self,
        git: GitClient | None = None,
        api: GitHubAPI | None = None,
        executor: TestExecutor | None = None,
    ) -> None:
        self.git = git or GitClient(token=settings.github_token)
        self.api = api or GitHubAPI(token=settings.github_token)
        self.executor = executor or PytestExecutor()

    async def publish(
        self, project: Project, task: Task, run: AgentRun, log: LogFn
    ) -> PublishResult:
        validate_github_project(project)
        if not run.file_changes:
            raise PublishError("The run has no file changes to publish")

        clone_dir = Path(tempfile.mkdtemp(prefix="agentforge-publish-"))
        try:
            log(f"cloning {project.github_owner}/{project.github_repo} "
                f"(branch {project.default_branch})")
            await self.git.clone(project.repo_url, clone_dir, project.default_branch)

            branch = branch_name_for(task)
            await self.git.create_branch(clone_dir, branch)
            log(f"created branch {branch}")

            for change in run.file_changes:
                await self.git.apply_diff(clone_dir, change.diff)
                log(f"applied diff: {change.path}")

            tests = await self.executor.run_tests(Workspace.from_dir(clone_dir))
            log(
                f"verification tests on fresh clone: {tests.passed} passed, "
                f"{tests.failed} failed, {tests.errored} errored"
            )
            if tests.failed or tests.errored:
                raise PublishError(
                    "Changes no longer pass tests on a fresh clone of "
                    f"{project.default_branch} ({tests.failed} failed, "
                    f"{tests.errored} errored) — the base branch may have moved. "
                    "Retry the task to regenerate the changes."
                )

            sha = await self.git.commit_all(clone_dir, task.title)
            log(f"committed {sha[:10]}")
            await self.git.push(clone_dir, project.repo_url, branch)
            log("pushed branch to origin")

            pr_url = await self.api.create_pull_request(
                owner=project.github_owner,
                repo=project.github_repo,
                head=branch,
                base=project.default_branch,
                title=task.title,
                body=(run.summary or task.request)
                + "\n\n---\n*Opened by AgentForge from an approved agent run.*",
            )
            log(f"pull request opened: {pr_url}")
            return PublishResult(branch_name=branch, commit_sha=sha, pr_url=pr_url)
        finally:
            shutil.rmtree(clone_dir, ignore_errors=True)


class PublishService:
    """Worker-side orchestration for the approve -> publish flow."""

    def __init__(
        self, session: AsyncSession, publisher: GitHubPublisher | None = None
    ) -> None:
        self.session = session
        self.publisher = publisher or GitHubPublisher()

    async def publish_task(self, task_id: int) -> None:
        from app.repositories.task_repo import TaskRepository

        task = await TaskRepository(self.session).get_with_runs(task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        if task.status != TaskStatus.publishing:
            logger.warning(
                "publish_task skipped: task %s is %s, not publishing", task_id, task.status
            )
            return
        project = await self.session.get(Project, task.project_id)

        run = next(
            (r for r in reversed(task.runs) if r.status == RunStatus.completed), None
        )
        if run is None:
            task.status = TaskStatus.failed
            await self.session.commit()
            raise NotFoundError(f"Task {task_id} has no successful run to publish")

        def log(message: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            run.log = (run.log or "") + f"\n[{stamp}] {message}"

        try:
            result = await self.publisher.publish(project, task, run, log)
            run.branch_name = result.branch_name
            run.commit_sha = result.commit_sha
            run.pr_url = result.pr_url
            run.error = None
            task.status = TaskStatus.completed
        except Exception as exc:
            logger.exception("Publish failed for task %s", task_id)
            log(f"publish failed: {exc}")
            run.error = str(exc)
            # Back to ready_for_review so the user can fix the cause and approve again.
            task.status = TaskStatus.ready_for_review
        await self.session.commit()
