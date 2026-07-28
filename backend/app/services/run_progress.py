"""Stage tracking, heartbeats and cancellation checkpoints for a live run.

One object owns the run's observable state: it advances the stage, writes the
heartbeat that proves the worker is alive, emits the event a client sees, and
answers "should I stop?" at each checkpoint.

Keeping these together is deliberate. They all have to happen at the same
moments, and splitting them was how the old code ended up with status
transitions in eleven places and no heartbeat at all.
"""

import logging
from datetime import datetime, timezone

from app.core.enums import RunStage, RunStatus, TaskEventType, TaskStatus
from app.core.task_state import (
    advance_progress,
    assert_transition,
    progress_for,
)
from app.models import AgentRun, Task

logger = logging.getLogger(__name__)


class RunCancelled(Exception):
    """Raised at a checkpoint when the user has asked to stop.

    Not an error: the caller records a cancelled run and preserves whatever
    was produced.
    """


class RunTracker:
    """Owns stage, progress, heartbeat, cancellation and event emission."""

    def __init__(
        self,
        session,
        task: Task,
        run: AgentRun,
        user_id: int,
        events=None,
        cancellation=None,
        lease=None,
        lock=None,
        publishing: bool = False,
    ) -> None:
        self.session = session
        self.task = task
        self.run = run
        self.user_id = user_id
        self._events = events
        self._cancellation = cancellation
        self._lease = lease
        self._lock = lock
        self._publishing = publishing

    # -- stage / progress --------------------------------------------------

    async def enter(
        self,
        stage: RunStage,
        message: str | None = None,
        task_status: TaskStatus | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Move to a stage: check for cancellation, advance state, emit.

        The cancellation check happens *first*, so a stop requested during the
        previous stage takes effect before any new work begins.
        """
        await self.checkpoint()

        self.run.stage = stage
        self.run.progress = advance_progress(
            self.run.progress, progress_for(stage, publishing=self._publishing)
        )
        if task_status is not None and task_status != self.task.status:
            # Rejects an illegal move instead of silently corrupting history.
            assert_transition(self.task.status, task_status)
            self.task.status = task_status
        await self.beat()
        await self.session.commit()

        await self.emit(
            TaskEventType.stage_changed,
            stage=stage,
            message=message,
            progress=self.run.progress,
            metadata=metadata,
        )

    async def beat(self) -> None:
        """Record liveness and renew the lease.

        A lapsed lease means another worker may have taken over, so we stop
        rather than race it.
        """
        self.run.heartbeat_at = datetime.now(timezone.utc)
        if self._lease is not None and self._lock is not None:
            if not await self._lock.renew(self._lease):
                logger.warning(
                    "Lease lost for task %s; another worker may have taken over",
                    self.task.id,
                )
                raise RunCancelled("Lease expired — another worker took over")

    # -- cancellation ------------------------------------------------------

    async def is_cancelled(self) -> bool:
        """Redis first for promptness, then the durable column.

        The database check is what makes a cancellation survive a Redis
        restart — it is still honoured at the next checkpoint.
        """
        if self.run.cancel_requested_at is not None:
            return True
        if self._cancellation is None:
            return False
        try:
            return await self._cancellation.is_requested(self.task.id)
        except Exception:
            # A KV outage must not be read as "cancelled".
            return False

    async def checkpoint(self) -> None:
        """Stop here if the user asked to. Called before and after every
        expensive or irreversible step."""
        if await self.is_cancelled():
            raise RunCancelled("Cancellation requested")

    # -- events ------------------------------------------------------------

    async def emit(
        self,
        event_type: TaskEventType,
        *,
        stage: RunStage | None = None,
        message: str | None = None,
        progress: int | None = None,
        error_code: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if self._events is None:
            return
        try:
            await self._events.emit(
                self.task,
                event_type,
                run=self.run,
                user_id=self.user_id,
                stage=stage or self.run.stage,
                message=message,
                progress=progress,
                error_code=error_code,
                metadata=metadata,
            )
        except Exception:
            # Observability must never take down the thing it observes.
            logger.warning("Could not emit %s for task %s", event_type, self.task.id)

    # -- terminal states ---------------------------------------------------

    async def finish(self, status: RunStatus, stage: RunStage) -> None:
        self.run.status = status
        self.run.stage = stage
        self.run.progress = advance_progress(
            self.run.progress, progress_for(stage, publishing=self._publishing)
        )
        self.run.finished_at = datetime.now(timezone.utc)

    async def fail(self, status: RunStatus, stage: RunStage, error_code: str,
                   message: str) -> None:
        await self.finish(status, stage)
        self.run.error_code = error_code
        self.run.error = message
