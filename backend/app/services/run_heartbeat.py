"""Proof that a long-running agent run is still alive.

Two mechanisms decide a worker has died, and both are shorter than a slow
model's generation step:

  * the reaper marks a run `abandoned` after STALE_AFTER_SECONDS without a
    heartbeat (5 minutes);
  * the execution lease expires after LEASE_SECONDS (2 minutes), after which
    a duplicate delivery could start a second worker on the same task.

`RunTracker.beat()` only fires at stage boundaries, and generation is a
single stage that can run for many minutes. Without something beating in
between, a perfectly healthy run is declared dead while it is still working
— which is exactly what happened to runs 16 and 17 on 2026-07-29.

This is the thirty-second beat the rest of the design already assumed.
"""

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone

from sqlalchemy import update

from app.core.enums import RunStatus
from app.models import AgentRun
from app.services.execution_lock import HEARTBEAT_SECONDS

logger = logging.getLogger(__name__)


class RunHeartbeat:
    """Beats for one run until stopped.

    Uses its own database session, deliberately: the run's session belongs to
    the coroutine doing the work, and an AsyncSession must never be shared
    between two concurrent tasks. A targeted UPDATE also avoids touching the
    ORM state that coroutine is holding.
    """

    def __init__(
        self,
        tracker,
        interval_seconds: int = HEARTBEAT_SECONDS,
        session_factory=None,
    ) -> None:
        self._tracker = tracker
        self._interval = interval_seconds
        self._run_id = tracker.run.id
        self._task: asyncio.Task | None = None
        if session_factory is None:
            from app.db.session import async_session_factory

            session_factory = async_session_factory
        self._session_factory = session_factory

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Idempotent, and safe to call when start() never ran."""
        if self._task is None:
            return
        task, self._task = self._task, None
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def __aenter__(self) -> "RunHeartbeat":
        await self.start()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.stop()

    # -- the beat ----------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.beat_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A transient database or Redis blip must never kill the run
                # this exists to protect. The next beat tries again, and there
                # is a whole STALE_AFTER_SECONDS of slack before it matters.
                logger.warning(
                    "Heartbeat failed for run %s", self._run_id, exc_info=True
                )

    async def beat_once(self) -> None:
        # Lease first: losing it is the more urgent of the two, and it flags
        # the tracker so the working coroutine stops at its next checkpoint.
        await self._tracker.renew_lease()
        async with self._session_factory() as session:
            await session.execute(
                update(AgentRun)
                .where(
                    AgentRun.id == self._run_id,
                    AgentRun.status == RunStatus.running,
                )
                .values(heartbeat_at=datetime.now(timezone.utc))
            )
            await session.commit()
