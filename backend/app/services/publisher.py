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
from app.core.enums import (
    ChangeType,
    ErrorCode,
    RunStage,
    RunStatus,
    TaskEventType,
    TaskStatus,
)
from app.core.exceptions import NotFoundError
from app.models import AgentRun, Project, Task
from app.services.git_client import GitAuthError, GitClient
from app.services.github_api import GitHubAPI, GitHubAuthError
from app.services.github_credentials import (
    GitCredentials,
    GitHubCredentialResolver,
    RepoOperation,
    RepositoryAccessError,
)
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
    """Turns an approved run into a pull request.

    Credentials are resolved separately for clone, push and PR creation, so a
    long verification run cannot carry a stale token into the write phase and
    access withdrawn mid-publish is caught before anything is written.
    """

    def __init__(
        self,
        git: GitClient | None = None,
        api: GitHubAPI | None = None,
        executor: TestExecutor | None | object = _DEFAULT_EXECUTOR,
        resolver: GitHubCredentialResolver | None = None,
        tracker=None,
    ) -> None:
        # An injected client keeps its own credentials (tests); otherwise one
        # is built per operation from freshly resolved credentials.
        self._injected_git = git
        # In github_app mode there is no PAT to fall back on, so the default
        # client carries no credential at all: every operation must build one
        # from freshly resolved credentials or fail.
        self.git = git or GitClient(
            token="" if settings.is_github_app_mode() else settings.github_token
        )
        self.api = api or GitHubAPI()
        self.resolver = resolver
        # Publishing emits through the same tracker the agent run uses, so
        # the SSE stream is continuous across both phases.
        self.tracker = tracker
        # None means "skip verification"; the default is pytest.
        self.executor: TestExecutor | None = (
            PytestExecutor() if executor is _DEFAULT_EXECUTOR else executor
        )

    async def _event(
        self,
        event_type,
        message: str,
        *,
        stage=None,
        error_code: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Emit a publish event when a tracker is present.

        Metadata passes through TaskEventService's allowlist, so a token or an
        authenticated URL cannot reach a client even if a caller passed one.
        """
        if self.tracker is None:
            return
        await self.tracker.emit(
            event_type,
            stage=stage,
            message=message,
            error_code=error_code,
            metadata=metadata,
        )

    async def _credentials(
        self, project: Project, operation: RepoOperation
    ) -> GitCredentials | None:
        """Resolve for one operation. None when a client was injected."""
        if self.resolver is None:
            return None
        return await self.resolver.resolve(
            project.id, operation, user_id=project.user_id
        )

    def _client_for(self, credentials: GitCredentials | None) -> GitClient:
        if self._injected_git is not None or credentials is None:
            return self.git
        return GitClient(
            token=credentials.token,
            committer_name=credentials.committer_name,
            committer_email=credentials.committer_email,
        )

    async def publish(
        self, project: Project, task: Task, run: AgentRun, log: LogFn
    ) -> PublishResult:
        validate_github_project(project)
        if not run.file_changes:
            raise PublishError("The run has no file changes to publish")

        await self._event(
            TaskEventType.publish_started,
            "Publishing started",
            stage=RunStage.pushing,
        )

        clone_dir = Path(tempfile.mkdtemp(prefix="agentforge-publish-"))
        try:
            clone_creds = await self._credentials(project, RepoOperation.clone)
            await self._event(
                TaskEventType.stage_changed,
                "Repository access verified",
                stage=RunStage.pushing,
                metadata={
                    # Names only — never the token or an authenticated URL.
                    "reason": "installation"
                    if clone_creds and clone_creds.is_installation
                    else "local"
                },
            )
            git = self._client_for(clone_creds)
            if clone_creds is not None:
                log(f"credential: {clone_creds.mode} "
                    f"(installation {clone_creds.github_installation_id})"
                    if clone_creds.is_installation
                    else "credential: local personal access token")
            log(f"cloning {project.github_owner}/{project.github_repo} "
                f"(branch {project.default_branch})")
            await self._event(
                TaskEventType.stage_changed,
                "Cloning repository",
                stage=RunStage.pushing,
            )
            await git.clone(project.repo_url, clone_dir, project.default_branch)
            await self._event(
                TaskEventType.stage_changed,
                "Repository cloned",
                stage=RunStage.pushing,
            )

            branch = branch_name_for(task)
            await git.create_branch(clone_dir, branch)
            log(f"created branch {branch}")

            for change in run.file_changes:
                if change.is_binary:
                    # Binary contents are not stored, so only deletions can be
                    # reproduced at publish time.
                    if change.change_type == ChangeType.delete:
                        await git.delete_path(clone_dir, change.path)
                        log(f"removed binary file: {change.path}")
                        continue
                    raise PublishError(
                        f"Run {change.change_type}s binary file {change.path!r}; "
                        "binary contents are not stored and cannot be published. "
                        "Make the change directly in the repository instead."
                    )
                await git.apply_diff(clone_dir, change.diff)
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

            sha = await git.commit_all(clone_dir, task.title)
            log(f"committed {sha[:10]}")

            # Re-resolve immediately before the first write: access may have
            # been withdrawn during verification, and the clone token may be
            # near expiry after a long test run.
            await self._push(project, clone_dir, branch, sha, log)

            pr_url = await self._open_pull_request(project, task, run, branch, log)
            return PublishResult(branch_name=branch, commit_sha=sha, pr_url=pr_url)
        finally:
            shutil.rmtree(clone_dir, ignore_errors=True)

    async def _push(
        self, project: Project, clone_dir: Path, branch: str, sha: str, log: LogFn
    ) -> None:
        """Push the branch, retrying once on an auth rejection.

        Push is not idempotent, so a retry first asks the remote whether the
        branch already carries our commit — a rejected response can arrive
        after the push actually landed.
        """
        await self._event(
            TaskEventType.stage_changed,
            f"Pushing branch {branch}",
            stage=RunStage.pushing,
            metadata={"branch": branch},
        )
        credentials = await self._credentials(project, RepoOperation.push)
        git = self._client_for(credentials)
        try:
            await git.push(clone_dir, project.repo_url, branch)
        except GitAuthError:
            if credentials is None:
                raise
            log("push rejected — revalidating access and retrying once")
            await self.resolver.invalidate(credentials)
            # Full revalidation: installation state and repository grant are
            # re-read, not just the token re-minted.
            credentials = await self._credentials(project, RepoOperation.push)
            git = self._client_for(credentials)
            existing = await git.remote_branch_sha(project.repo_url, branch)
            if existing == sha:
                log("branch already present on origin — first push had landed")
                return
            await git.push(clone_dir, project.repo_url, branch)
        log("pushed branch to origin")
        await self._event(
            TaskEventType.branch_pushed,
            f"Branch {branch} pushed",
            stage=RunStage.pushing,
            metadata={"branch": branch, "commit_sha": sha},
        )

    async def _open_pull_request(
        self, project: Project, task: Task, run: AgentRun, branch: str, log: LogFn
    ) -> str:
        """Open the PR, retrying once on an auth rejection.

        Creating a PR is not idempotent either, so a retry checks for an
        existing PR on this head branch before opening another.
        """
        body = (run.summary or task.request) + (
            "\n\n---\n*Opened by AgentForge from an approved agent run.*"
        )
        await self._event(
            TaskEventType.stage_changed,
            "Creating pull request",
            stage=RunStage.creating_pr,
            metadata={"branch": branch},
        )
        credentials = await self._credentials(project, RepoOperation.pull_request)
        if credentials is None and settings.is_github_app_mode():
            raise RepositoryAccessError(
                "GitHub App access to this repository is no longer available. "
                "Reinstall or update repository access."
            )
        token = credentials.token if credentials else settings.github_token
        try:
            pr_url = await self.api.create_pull_request(
                owner=project.github_owner,
                repo=project.github_repo,
                head=branch,
                base=project.default_branch,
                title=task.title,
                body=body,
                token=token,
            )
        except GitHubAuthError:
            if credentials is None:
                raise
            log("pull request rejected — revalidating access and retrying once")
            await self.resolver.invalidate(credentials)
            credentials = await self._credentials(project, RepoOperation.pull_request)
            existing = await self.api.find_pull_request(
                project.github_owner, project.github_repo, branch, credentials.token
            )
            if existing:
                log(f"pull request already existed: {existing}")
                return existing
            pr_url = await self.api.create_pull_request(
                owner=project.github_owner,
                repo=project.github_repo,
                head=branch,
                base=project.default_branch,
                title=task.title,
                body=body,
                token=credentials.token,
            )
        log(f"pull request opened: {pr_url}")
        await self._event(
            TaskEventType.pr_created,
            "Pull request opened",
            stage=RunStage.creating_pr,
            metadata={"pr_url": pr_url, "branch": branch},
        )
        return pr_url


class PublishService:
    """Worker-side orchestration for the approve -> publish flow."""

    def __init__(
        self,
        session: AsyncSession,
        publisher: GitHubPublisher | None = None,
        events=None,
    ) -> None:
        self.session = session
        self._injected = publisher is not None
        self._events = events
        if publisher is None:
            from app.services.github_app_token_service import GitHubAppTokenService
            from app.services.kv_store import get_shared_kv

            token_service = (
                GitHubAppTokenService(get_shared_kv())
                if settings.is_github_app_mode()
                else None
            )
            publisher = GitHubPublisher(
                resolver=GitHubCredentialResolver(session, token_service)
            )
        self.publisher = publisher

    async def publish_task(self, task_id: int) -> None:
        from app.repositories.task_repo import TaskRepository

        # Worker context: no request user. Ownership is re-derived from the
        # project row rather than trusted from the job payload.
        task = await TaskRepository(self.session).get_with_runs_unscoped_for_worker(
            task_id
        )
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

        # Publishing shares the run's tracker so its events land on the same
        # SSE stream, with per-run sequence numbers continuing uninterrupted.
        if self._events is not None and self.publisher.tracker is None:
            from app.services.run_progress import RunTracker

            self.publisher.tracker = RunTracker(
                self.session,
                task,
                run,
                user_id=project.user_id,
                events=self._events,
                publishing=True,
            )

        failure_code: str | None = None
        # Captured before the try: after a rollback these instances are
        # expired, and reading an attribute would trigger a lazy load.
        ids = (task.id, run.id, project.user_id)
        try:
            result = await self.publisher.publish(project, task, run, log)
            run.branch_name = result.branch_name
            run.commit_sha = result.commit_sha
            run.pr_url = result.pr_url
            run.error = None
            task.status = TaskStatus.completed
        except RepositoryAccessError as exc:
            # Access was withdrawn between approval and publish. The run's
            # diffs and history are preserved; only publishing is blocked, and
            # the task returns to review so it can be retried once restored.
            logger.warning("Publish blocked for task %s: %s", task_id, exc)
            await self.session.rollback()
            log(f"publish blocked: {exc}")
            run.error = str(exc)
            run.error_code = ErrorCode.repository_access_lost
            task.status = TaskStatus.ready_for_review
            failure_code = ErrorCode.repository_access_lost
        except Exception as exc:
            logger.exception("Publish failed for task %s", task_id)
            # A flush error leaves the session unusable until rolled back.
            await self.session.rollback()
            log(f"publish failed: {exc}")
            from app.core.error_codes import classify

            code = classify(exc)
            run.error = str(exc)
            run.error_code = code
            # Back to ready_for_review so the user can fix the cause and approve again.
            task.status = TaskStatus.ready_for_review
            failure_code = code
        await self.session.commit()

        # Emitted only after the commit: inside the handler the session is
        # mid-rollback and the instances are expired, so writing an event
        # there would fail on a lazy load.
        if failure_code is not None:
            await self._publish_failed(*ids, failure_code)

    async def _publish_failed(
        self, task_id: int, run_id: int, user_id: int, code: str
    ) -> None:
        """Announce a blocked or failed publish.

        Takes ids rather than instances: by the time this runs the session has
        been rolled back and re-committed, so the originals are expired.

        The message comes from the error catalogue, never from the exception —
        a raw message can carry a path, a command, or an upstream response.
        Generated changes are untouched; only publishing stopped.
        """
        if self._events is None:
            return
        from app.core.error_codes import describe

        try:
            task = await self.session.get(Task, task_id)
            run = await self.session.get(AgentRun, run_id)
            if task is None:
                return
            await self._events.emit(
                task,
                TaskEventType.publish_failed,
                run=run,
                user_id=user_id,
                stage=RunStage.failed,
                message=describe(code).message,
                error_code=code,
            )
        except Exception:
            logger.warning("Could not emit publish failure for task %s", task_id)
