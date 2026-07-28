import logging
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.executor import (
    CommandExecutor,
    PytestExecutor,
    TestExecutor,
    TestResultData,
)
from app.agent.runner import AgentRunner, get_mock_runner
from app.agent.workspace import Workspace
from app.core.config import settings
from app.core.enums import AgentMode, RunStatus, TaskStatus
from app.core.exceptions import ConflictError, NotFoundError
from app.llm.profiles import resolve_specs
from app.llm.service import LLMService
from app.models import AgentRun, FileChange, Project, Task, TestResult
from app.services.git_client import GitClient
from app.services.github_config import is_github_project, validate_github_project
from app.services.github_credentials import RepoOperation
from app.core.enums import RunStage, TaskEventType
from app.core.enums import ErrorCode
from app.core.error_codes import classify, describe
from app.core.task_state import assert_transition, is_terminal_task, reconcile
from app.services.run_progress import RunCancelled, RunTracker

logger = logging.getLogger(__name__)

WorkspaceFactory = Callable[[Project], Awaitable[Workspace]]


async def create_workspace_for(
    project: Project, session=None
) -> Workspace:
    """Sample-repo copy, or a shallow clone for GitHub-configured projects.

    In github_app mode the clone credential is resolved from the project's
    installation — validated for ownership, installation state and repository
    grant — and discarded once the clone completes.
    """
    if not is_github_project(project):
        return Workspace.create_from(settings.sample_repo_path)
    # Fails clearly here (before any agent work) if config is missing.
    validate_github_project(project)

    git = await build_git_client(project, session, RepoOperation.clone)
    clone_dir = Path(tempfile.mkdtemp(prefix="agentforge-ws-"))
    await git.clone(project.repo_url, clone_dir, project.default_branch)
    return Workspace.from_dir(clone_dir)


async def build_git_client(
    project: Project, session, operation: "RepoOperation"
) -> GitClient:
    """A git client carrying freshly resolved credentials for one operation."""
    if session is None:
        # No session means no way to resolve an installation credential. In
        # github_app mode that must abort, never silently reach for the PAT.
        if settings.is_github_app_mode():
            from app.services.github_credentials import RepositoryAccessError

            raise RepositoryAccessError(
                "GitHub App access to this repository is no longer available. "
                "Reinstall or update repository access."
            )
        return GitClient(
            token=settings.github_token,
            committer_name=settings.local_commit_name,
            committer_email=settings.local_commit_email,
        )
    from app.services.github_app_token_service import GitHubAppTokenService
    from app.services.github_credentials import GitHubCredentialResolver
    from app.services.kv_store import get_shared_kv

    token_service = (
        GitHubAppTokenService(get_shared_kv())
        if settings.is_github_app_mode()
        else None
    )
    credentials = await GitHubCredentialResolver(session, token_service).resolve(
        project.id, operation, user_id=project.user_id
    )
    return GitClient(
        token=credentials.token,
        committer_name=credentials.committer_name,
        committer_email=credentials.committer_email,
    )


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
        events=None,
        cancellation=None,
        lock=None,
        lease=None,
    ) -> None:
        self.session = session
        self._runner = runner
        self._executor = executor
        self._events = events
        self._cancellation = cancellation
        self._lock = lock
        self._lease = lease
        self._workspace_factory = workspace_factory or (
            lambda project: create_workspace_for(project, session)
        )

    async def _resolve_executor(self, project: Project) -> TestExecutor | None:
        """Pick the test executor; None means 'honestly skip tests'."""
        if self._executor is not None:
            return self._executor
        if is_github_project(project):
            from app.services.analysis_service import latest_completed_analysis

            analysis = await latest_completed_analysis(self.session, project.id)
            if analysis is not None:
                if analysis.test_command:
                    return CommandExecutor(analysis.test_command)
                return None  # analyzed and no test command detected
        return PytestExecutor()

    async def execute_agent_run(self, task_id: int) -> AgentRun:
        task = await self.session.get(Task, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        # Duplicate-execution guard: a finished task must not be re-run by a
        # redelivered job. Refuse plainly rather than failing partway through
        # and then failing again inside the error handler.
        if is_terminal_task(task.status):
            raise ConflictError(
                f"Task {task_id} is {task.status} and cannot be executed again"
            )
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

        tracker = RunTracker(
            self.session,
            task,
            run,
            user_id=project.user_id,
            events=self._events,
            cancellation=self._cancellation,
            lease=self._lease,
            lock=self._lock,
        )
        await tracker.emit(
            TaskEventType.run_started,
            stage=RunStage.queued,
            message="Run started",
            progress=0,
        )

        log_lines: list[str] = []

        def log(message: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            log_lines.append(f"[{stamp}] {message}")
            run.log = "\n".join(log_lines)

        workspace: Workspace | None = None
        try:
            runner = self._runner or self._build_runner(task, project, run)
            # Fallback notices ("... unavailable; continued with ...") from
            # the LLM gateway land in this run's log.
            inner_service = getattr(runner, "service", None)
            if inner_service is not None and inner_service.log is None:
                inner_service.log = log
            # Record the mode actually used (an injected runner may differ
            # from the configured AGENT_MODE).
            run.mode = runner.mode
            log(f"agent run started (mode={runner.mode})")
            if runner.mode == AgentMode.llm:
                specs = getattr(runner, "specs", {})
                described = {
                    phase: f"{s.provider}/{s.model}" for phase, s in specs.items()
                }
                log(f"llm configuration: {described}")

            await tracker.enter(RunStage.preparing, "Preparing workspace")
            await tracker.enter(
                RunStage.cloning,
                "Cloning repository"
                if is_github_project(project)
                else "Copying sample repository",
            )
            workspace = await self._workspace_factory(project)
            source = (
                f"clone of {project.github_owner}/{project.github_repo}"
                if is_github_project(project)
                else "sample repo copy"
            )
            log(f"workspace ready: {len(workspace.list_files())} files ({source})")

            await tracker.enter(
                RunStage.planning, "Planning the change", TaskStatus.planning
            )
            run.plan = await runner.generate_plan(task.title, task.request, workspace)
            await tracker.checkpoint()
            log(f"plan generated ({len(run.plan)} steps)")
            await self.session.commit()

            await tracker.enter(
                RunStage.generating, "Generating changes", TaskStatus.coding
            )
            await runner.apply_changes(
                task.title, task.request, run.plan, workspace, log
            )
            # Generation is the longest step; stop here if asked, before any
            # further work is done on changes we are about to discard.
            await tracker.checkpoint()
            changes = workspace.compute_changes()
            for change in changes:
                run.file_changes.append(
                    FileChange(
                        path=change.path,
                        change_type=change.change_type,
                        diff=change.diff,
                        is_binary=change.is_binary,
                        size_bytes=change.size_bytes,
                        content_hash=change.content_hash,
                    )
                )
                if change.is_binary:
                    log(
                        f"binary file {change.change_type}: {change.path} "
                        "(metadata only — textual diff unavailable)"
                    )
            log(f"{len(changes)} file(s) changed")
            await self.session.commit()
            await tracker.emit(
                TaskEventType.file_changed,
                message=f"{len(changes)} file(s) changed",
                metadata={"files_changed": len(changes)},
            )

            executor = await self._resolve_executor(project)
            if executor is None:
                tests = TestResultData(
                    suite="none",
                    passed=0,
                    failed=0,
                    errored=0,
                    duration=0.0,
                    output="No automated test command detected.",
                    stderr="",
                )
                tests_ran = False
                log(
                    "No automated test command detected — skipping test phase "
                    "(changes are unverified)"
                )
            else:
                await tracker.enter(
                    RunStage.testing, "Running tests", TaskStatus.testing
                )
                await tracker.emit(
                    TaskEventType.tests_started, message="Running tests"
                )
                tests = await executor.run_tests(workspace)
                tests_ran = True
                await tracker.emit(
                    TaskEventType.tests_completed,
                    message=(
                        f"{tests.passed} passed, {tests.failed} failed, "
                        f"{tests.errored} errored"
                    ),
                    metadata={
                        "suite": tests.suite,
                        "passed": tests.passed,
                        "failed": tests.failed,
                        "errored": tests.errored,
                        "duration": tests.duration,
                    },
                )
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
                    f"tests ({tests.suite}): {tests.passed} passed, "
                    f"{tests.failed} failed, {tests.errored} errored "
                    f"in {tests.duration}s"
                )
            await self.session.commit()

            await tracker.enter(RunStage.summarising, "Writing the summary")
            run.summary = await runner.summarize(
                task.title, task.request, run.plan, changes, tests
            )

            tests_green = tests.failed == 0 and tests.errored == 0
            # One place decides how a finished run maps onto the task, so the
            # two can no longer contradict each other.
            final_status = reconcile(
                RunStatus.completed,
                tests_green=tests_green,
                has_changes=bool(changes),
                is_github=is_github_project(project),
            )
            await tracker.finish(RunStatus.completed, RunStage.awaiting_review
                                 if final_status == TaskStatus.ready_for_review
                                 else RunStage.completed)
            assert_transition(task.status, final_status)
            task.status = final_status

            if final_status == TaskStatus.ready_for_review:
                if tests_ran:
                    log("tests passed — ready for review; approve to create a pull request")
                else:
                    log(
                        "ready for review WITHOUT test verification — "
                        "review the diff carefully before approving"
                    )
            else:
                if is_github_project(project):
                    log(
                        "run complete — no pull request possible "
                        + ("(tests failed)" if not tests_green else "(no file changes)")
                    )
                else:
                    log("summary written — run complete")
            await self.session.commit()
            await tracker.emit(
                TaskEventType.review_ready
                if final_status == TaskStatus.ready_for_review
                else TaskEventType.stage_changed,
                message=(
                    "Ready for review"
                    if final_status == TaskStatus.ready_for_review
                    else "Run complete"
                ),
                progress=100,
                metadata={"files_changed": len(changes)},
            )
        except RunCancelled:
            # Not a failure: stop cleanly and keep everything produced so far.
            await self.session.rollback()
            log("run cancelled by request")
            await tracker.fail(
                RunStatus.cancelled,
                RunStage.cancelled,
                ErrorCode.cancelled,
                "Cancelled by request",
            )
            if task.status != TaskStatus.cancelled:
                assert_transition(task.status, TaskStatus.cancelled)
                task.status = TaskStatus.cancelled
            await self.session.commit()
            await tracker.emit(
                TaskEventType.run_cancelled,
                stage=RunStage.cancelled,
                message="Run cancelled",
                error_code=ErrorCode.cancelled,
            )
            if self._cancellation is not None:
                try:
                    await self._cancellation.clear(task.id)
                except Exception:
                    pass
        except Exception as exc:
            logger.exception("Agent run failed for task %s", task_id)
            # A flush error leaves the session unusable until rolled back.
            await self.session.rollback()
            log(f"run failed: {exc}")
            code = classify(exc)
            await tracker.fail(RunStatus.failed, RunStage.failed, code, str(exc))
            if task.status != TaskStatus.failed:
                assert_transition(task.status, TaskStatus.failed)
                task.status = TaskStatus.failed
            await self.session.commit()
            await tracker.emit(
                TaskEventType.run_failed,
                stage=RunStage.failed,
                message=describe(code).message,
                error_code=code,
            )
        finally:
            if workspace is not None:
                workspace.cleanup()

        return run

    def _build_runner(self, task: Task, project: Project, run: AgentRun) -> AgentRunner:
        if settings.agent_mode == AgentMode.mock:
            return get_mock_runner()
        from app.agent.llm_runner import LLMRunner

        specs = resolve_specs(
            task.llm_provider,
            task.llm_model,
            task.execution_profile,
            project.preferred_provider,
            project.preferred_model,
            project.preferred_execution_profile,
        )
        service = LLMService(
            self.session, project_id=project.id, agent_run_id=run.id
        )
        return LLMRunner(service=service, specs=specs)

    async def _set_status(self, task: Task, status: TaskStatus) -> None:
        task.status = status
        await self.session.commit()
