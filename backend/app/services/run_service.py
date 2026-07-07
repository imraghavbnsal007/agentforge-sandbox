import logging
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.executor import PytestExecutor, TestExecutor
from app.agent.runner import AgentRunner, get_runner
from app.agent.workspace import Workspace
from app.core.config import settings
from app.core.enums import RunStatus, TaskStatus
from app.core.exceptions import NotFoundError
from app.models import AgentRun, FileChange, Project, Task, TestResult
from app.services.git_client import GitClient
from app.services.publisher import validate_github_project

logger = logging.getLogger(__name__)

WorkspaceFactory = Callable[[Project], Awaitable[Workspace]]


def is_github_project(project: Project) -> bool:
    return bool(project.repo_url or project.github_owner or project.github_repo)


async def create_workspace_for(project: Project) -> Workspace:
    """Sample-repo copy, or a shallow clone for GitHub-configured projects."""
    if not is_github_project(project):
        return Workspace.create_from(settings.sample_repo_path)
    # Fails clearly here (before any agent work) if config or token is missing.
    validate_github_project(project)
    clone_dir = Path(tempfile.mkdtemp(prefix="agentforge-ws-"))
    git = GitClient(token=settings.github_token)
    await git.clone(project.repo_url, clone_dir, project.default_branch)
    return Workspace.from_dir(clone_dir)


class RunService:
    """Executes one agent run: workspace setup, status transitions, artifacts.

    Pipeline: copy sample repo to a scratch workspace -> plan -> agent edits
    the workspace -> compute diffs -> run pytest -> PR-style summary. Each
    phase commits so the UI sees live status and log updates.
    """

    def __init__(
        self,
        session: AsyncSession,
        runner: AgentRunner | None = None,
        executor: TestExecutor | None = None,
        workspace_factory: WorkspaceFactory | None = None,
    ) -> None:
        self.session = session
        self._runner = runner
        self._executor = executor or PytestExecutor()
        self._workspace_factory = workspace_factory or create_workspace_for

    async def execute_agent_run(self, task_id: int) -> AgentRun:
        task = await self.session.get(Task, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        project = await self.session.get(Project, task.project_id)

        # Collections are passed explicitly so they are marked loaded; a first
        # access after commit would otherwise trigger a sync lazy-load, which
        # raises MissingGreenlet inside the async session.
        run = AgentRun(
            task_id=task.id,
            mode=settings.agent_mode,
            file_changes=[],
            test_results=[],
        )
        self.session.add(run)
        await self.session.commit()

        log_lines: list[str] = []

        def log(message: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            log_lines.append(f"[{stamp}] {message}")
            run.log = "\n".join(log_lines)

        workspace: Workspace | None = None
        try:
            runner = self._runner or get_runner(settings.agent_mode)
            # Record the mode actually used (an injected runner may differ
            # from the configured AGENT_MODE).
            run.mode = runner.mode
            log(f"agent run started (mode={runner.mode})")

            workspace = await self._workspace_factory(project)
            source = (
                f"clone of {project.github_owner}/{project.github_repo}"
                if is_github_project(project)
                else "sample repo copy"
            )
            log(f"workspace ready: {len(workspace.list_files())} files ({source})")

            await self._set_status(task, TaskStatus.planning)
            run.plan = await runner.generate_plan(task.title, task.request, workspace)
            log(f"plan generated ({len(run.plan)} steps)")
            await self.session.commit()

            await self._set_status(task, TaskStatus.coding)
            await runner.apply_changes(
                task.title, task.request, run.plan, workspace, log
            )
            changes = workspace.compute_changes()
            for change in changes:
                run.file_changes.append(
                    FileChange(
                        path=change.path,
                        change_type=change.change_type,
                        diff=change.diff,
                    )
                )
            log(f"{len(changes)} file(s) changed")
            await self.session.commit()

            await self._set_status(task, TaskStatus.testing)
            tests = await self._executor.run_tests(workspace)
            run.test_results.append(
                TestResult(
                    suite=tests.suite,
                    passed=tests.passed,
                    failed=tests.failed,
                    errored=tests.errored,
                    duration=tests.duration,
                    output=tests.output,
                    stderr=tests.stderr,
                )
            )
            log(
                f"tests: {tests.passed} passed, {tests.failed} failed, "
                f"{tests.errored} errored in {tests.duration}s"
            )
            await self.session.commit()

            run.summary = await runner.summarize(
                task.title, task.request, run.plan, changes, tests
            )
            run.status = RunStatus.completed
            run.finished_at = datetime.now(timezone.utc)
            tests_green = tests.failed == 0 and tests.errored == 0
            if is_github_project(project) and tests_green and changes:
                task.status = TaskStatus.ready_for_review
                log("tests passed — ready for review; approve to create a pull request")
            else:
                task.status = TaskStatus.completed
                if is_github_project(project):
                    log(
                        "run complete — no pull request possible "
                        + ("(tests failed)" if not tests_green else "(no file changes)")
                    )
                else:
                    log("summary written — run complete")
            await self.session.commit()
        except Exception as exc:
            logger.exception("Agent run failed for task %s", task_id)
            log(f"run failed: {exc}")
            run.status = RunStatus.failed
            run.error = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            task.status = TaskStatus.failed
            await self.session.commit()
        finally:
            if workspace is not None:
                workspace.cleanup()

        return run

    async def _set_status(self, task: Task, status: TaskStatus) -> None:
        task.status = status
        await self.session.commit()
