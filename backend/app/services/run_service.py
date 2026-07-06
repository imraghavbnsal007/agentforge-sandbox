import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import AgentRunner, get_runner
from app.core.config import settings
from app.core.enums import RunStatus, TaskStatus
from app.core.exceptions import NotFoundError
from app.models import AgentRun, FileChange, Task, TestResult

logger = logging.getLogger(__name__)


class RunService:
    """Executes one agent run: drives task status transitions and records artifacts."""

    def __init__(self, session: AsyncSession, runner: AgentRunner | None = None) -> None:
        self.session = session
        self._runner = runner

    async def execute_agent_run(self, task_id: int) -> AgentRun:
        task = await self.session.get(Task, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")

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

        try:
            runner = self._runner or get_runner(settings.agent_mode)

            await self._set_status(task, TaskStatus.planning)
            run.plan = await runner.generate_plan(task.title, task.request)
            await self.session.commit()

            await self._set_status(task, TaskStatus.coding)
            changes = await runner.apply_changes(task.title, task.request)
            for change in changes:
                run.file_changes.append(
                    FileChange(
                        path=change.path,
                        change_type=change.change_type,
                        diff=change.diff,
                    )
                )
            await self.session.commit()

            await self._set_status(task, TaskStatus.testing)
            tests = await runner.run_tests(task.title, task.request)
            run.test_results.append(
                TestResult(
                    suite=tests.suite,
                    passed=tests.passed,
                    failed=tests.failed,
                    errored=tests.errored,
                    duration=tests.duration,
                    output=tests.output,
                )
            )
            run.summary = await runner.summarize(
                task.title, task.request, run.plan, changes, tests
            )
            run.status = RunStatus.completed
            run.finished_at = datetime.now(timezone.utc)
            task.status = TaskStatus.completed
            await self.session.commit()
        except Exception as exc:
            logger.exception("Agent run failed for task %s", task_id)
            run.status = RunStatus.failed
            run.error = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            task.status = TaskStatus.failed
            await self.session.commit()

        return run

    async def _set_status(self, task: Task, status: TaskStatus) -> None:
        task.status = status
        await self.session.commit()
