"""Recovering runs whose worker died.

Before Phase 7 a crashed worker left its task in `coding` forever: the row
still said `running`, nothing was renewing anything, and there was no way to
tell a long model call from a dead process.

A heartbeat is that distinction. This module finds `running` rows whose
heartbeat has gone stale, marks them `abandoned`, and moves the task to a
state the user can act on — **without discarding anything the run produced**.
Diffs, logs and test results are exactly where they were.

Nothing here re-runs work automatically. A non-idempotent operation
(push, pull request) may or may not have completed before the crash, so the
decision to retry is deliberately left to the user, who gets a clear message.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ErrorCode,
    RunStage,
    RunStatus,
    TaskEventType,
    TaskStatus,
)
from app.core.task_state import assert_transition, can_transition
from app.models import AgentRun, Project, Task
from app.services.execution_lock import is_stale

logger = logging.getLogger(__name__)


async def find_stale_runs(session: AsyncSession) -> list[AgentRun]:
    """Runs still marked running whose worker has stopped reporting."""
    result = await session.execute(
        select(AgentRun).where(AgentRun.status == RunStatus.running)
    )
    now = datetime.now(timezone.utc)
    return [run for run in result.scalars().all() if is_stale(run, now)]


async def reap_stale_runs(session: AsyncSession, events=None) -> int:
    """Mark abandoned runs and free their tasks. Returns how many."""
    stale = await find_stale_runs(session)
    if not stale:
        return 0

    now = datetime.now(timezone.utc)
    for run in stale:
        run.status = RunStatus.abandoned
        run.stage = RunStage.failed
        run.finished_at = now
        run.error_code = ErrorCode.worker_interrupted
        run.error = (
            "The worker stopped before this run finished. Any changes "
            "produced before the interruption have been preserved."
        )

        task = await session.get(Task, run.task_id)
        if task is None:
            continue
        # `failed` is reachable from every active state, so this cannot itself
        # raise; the guard is here so an unexpected state is loud, not silent.
        if can_transition(task.status, TaskStatus.failed):
            assert_transition(task.status, TaskStatus.failed)
            task.status = TaskStatus.failed
        else:
            logger.warning(
                "Task %s is %s; leaving it alone while reaping run %s",
                task.id,
                task.status,
                run.id,
            )

        if events is not None:
            project = await session.get(Project, task.project_id)
            try:
                await events.emit(
                    task,
                    TaskEventType.run_failed,
                    run=run,
                    user_id=project.user_id if project else 0,
                    stage=RunStage.failed,
                    message=(
                        "The worker stopped before this run finished. Retry to "
                        "start a fresh run."
                    ),
                    error_code=ErrorCode.worker_interrupted,
                )
            except Exception:
                logger.warning("Could not emit abandonment event for run %s", run.id)

    await session.commit()
    logger.info("Reaped %d abandoned run(s)", len(stale))
    return len(stale)


async def publish_needs_manual_check(run: AgentRun) -> bool:
    """Whether a crashed publish may already have changed the remote.

    A run that got as far as pushing might have created the branch, or even
    the pull request, before dying. Blindly retrying could duplicate either,
    so the publisher reconciles remote state first — see GitHubPublisher._push
    and ._open_pull_request, which check before they retry.
    """
    return run.stage in (RunStage.pushing, RunStage.creating_pr) and not run.pr_url
