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
from app.core.enums import ChangeType, RunStatus, TaskStatus
from app.core.exceptions import NotFoundError
from app.models import AgentRun, Project, Task
from app.services.git_client import GitClient
from app.services.github_api import GitHubAPI
from app.services.github_config import (  # noqa: F401  (re-exported for callers)
    PublishError,
    validate_github_project,
)

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    branch_name: str
    commit_sha: str
    pr_url: str


def branch_name_for(task: Task) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task.title.lower()).strip("-")[:40].rstrip("-")
    return f"agentforge/task-{task.id}-{slug or 'change'}"


_DEFAULT_EXECUTOR = object()


class GitHubPublisher:
    def __init__(
        self,
        git: GitClient | None = None,
        api: GitHubAPI | None = None,
        executor: TestExecutor | None | object = _DEFAULT_EXECUTOR,
    ) -> None:
        self.git = git or GitClient(token=settings.github_token)
        self.api = api or GitHubAPI(token=settings.github_token)
        # None means "skip verification"; the default is pytest.
        self.executor: TestExecutor | None = (
            PytestExecutor() if executor is _DEFAULT_EXECUTOR else executor
        )

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
                if change.is_binary:
                    # Binary contents are not stored, so only deletions can be
                    # reproduced at publish time.
                    if change.change_type == ChangeType.delete:
                        await self.git.delete_path(clone_dir, change.path)
                        log(f"removed binary file: {change.path}")
                        continue
                    raise PublishError(
                        f"Run {change.change_type}s binary file {change.path!r}; "
                        "binary contents are not stored and cannot be published. "
                        "Make the change directly in the repository instead."
                    )
                await self.git.apply_diff(clone_dir, change.diff)
                log(f"applied diff: {change.path}")

            if self.executor is None:
                log(
                    "verification skipped — no automated test command detected "
                    "for this repository"
                )
            else:
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
        self._injected = publisher is not None
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

        # Read the existing log once, up front: after a rollback the instance
        # is expired and a read would trigger a sync lazy-load (MissingGreenlet).
        base_log = run.log or ""
        log_lines: list[str] = []

        def log(message: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            log_lines.append(f"[{stamp}] {message}")
            run.log = base_log + "\n" + "\n".join(log_lines)

        # Use the project's detected test command for the verification gate
        # (or skip it honestly if analysis found none).
        if not self._injected:
            from app.agent.executor import CommandExecutor
            from app.services.analysis_service import latest_completed_analysis

            analysis = await latest_completed_analysis(self.session, project.id)
            if analysis is not None:
                self.publisher.executor = (
                    CommandExecutor(analysis.test_command)
                    if analysis.test_command
                    else None
                )

        try:
            result = await self.publisher.publish(project, task, run, log)
            run.branch_name = result.branch_name
            run.commit_sha = result.commit_sha
            run.pr_url = result.pr_url
            run.error = None
            task.status = TaskStatus.completed
        except Exception as exc:
            logger.exception("Publish failed for task %s", task_id)
            # A flush error leaves the session unusable until rolled back.
            await self.session.rollback()
            log(f"publish failed: {exc}")
            run.error = str(exc)
            # Back to ready_for_review so the user can fix the cause and approve again.
            task.status = TaskStatus.ready_for_review
        await self.session.commit()
