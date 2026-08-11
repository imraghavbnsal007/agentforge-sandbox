"""The beat that keeps a long run from being declared dead.

Runs 16 and 17 (2026-07-29) were killed by the reaper while the worker was
still happily calling the model: the last heartbeat was three seconds into a
nine-minute run, because `beat()` only fires at stage boundaries and
generation is a single stage.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RunStage, RunStatus
from app.models import AgentRun, Task
from app.services.execution_lock import HEARTBEAT_SECONDS, STALE_AFTER_SECONDS, is_stale
from app.services.run_heartbeat import RunHeartbeat
from app.services.run_progress import RunCancelled, RunTracker


async def _running_run(session: AsyncSession, task: Task, age: int = 0) -> AgentRun:
    started = datetime.now(timezone.utc) - timedelta(seconds=age)
    run = AgentRun(
        task_id=task.id,
        mode="mock",
        status=RunStatus.running,
        stage=RunStage.generating,
        started_at=started,
        heartbeat_at=started,
        file_changes=[],
        test_results=[],
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


def _tracker(session, task, run, **kwargs) -> RunTracker:
    return RunTracker(session, task, run, user_id=1, **kwargs)


class SharedSession:
    """Lends the test's session to the beater without closing it.

    In production the beater opens its own session and closes it — sharing one
    across two coroutines is the thing it exists to avoid. Tests are
    single-threaded, so reusing the fixture session is safe as long as the
    beater's `async with` does not detach every instance on the way out.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc_info) -> None:
        return None


def _factory(session: AsyncSession):
    return lambda: SharedSession(session)


class FakeLock:
    def __init__(self, renewable: bool = True) -> None:
        self.renewable = renewable
        self.renewals = 0

    async def renew(self, lease) -> bool:
        self.renewals += 1
        return self.renewable


# -- the beat itself --------------------------------------------------------


async def test_a_beat_moves_the_heartbeat_forward(
    session: AsyncSession, task: Task
) -> None:
    run = await _running_run(session, task, age=120)
    before = run.heartbeat_at

    beater = RunHeartbeat(
        _tracker(session, task, run), session_factory=_factory(session)
    )
    await beater.beat_once()

    await session.refresh(run)
    assert run.heartbeat_at > before


async def test_beating_rescues_a_run_the_reaper_would_have_taken(
    session: AsyncSession, task: Task
) -> None:
    """The whole point: a long generation step stays visibly alive."""
    run = await _running_run(session, task, age=STALE_AFTER_SECONDS + 60)
    assert is_stale(run, datetime.now(timezone.utc))

    beater = RunHeartbeat(
        _tracker(session, task, run), session_factory=_factory(session)
    )
    await beater.beat_once()

    await session.refresh(run)
    assert not is_stale(run, datetime.now(timezone.utc))


async def test_a_finished_run_is_not_kept_artificially_alive(
    session: AsyncSession, task: Task
) -> None:
    """A late beat must not resurrect a run that already reached a terminal
    state, or the reaper could never clean up after a stuck beater."""
    run = await _running_run(session, task, age=600)
    run.status = RunStatus.completed
    await session.commit()
    before = run.heartbeat_at

    beater = RunHeartbeat(
        _tracker(session, task, run), session_factory=_factory(session)
    )
    await beater.beat_once()

    await session.refresh(run)
    assert run.heartbeat_at == before


# -- the lease --------------------------------------------------------------


async def test_a_beat_renews_the_execution_lease(
    session: AsyncSession, task: Task
) -> None:
    """The lease expires after 120s — sooner than the reaper's window — so a
    long run would otherwise let a duplicate delivery start a second worker."""
    run = await _running_run(session, task)
    lock = FakeLock()
    beater = RunHeartbeat(
        _tracker(session, task, run, lock=lock, lease=object()),
        session_factory=_factory(session),
    )

    await beater.beat_once()
    assert lock.renewals == 1


async def test_losing_the_lease_stops_the_run_at_the_next_checkpoint(
    session: AsyncSession, task: Task
) -> None:
    """The beater cannot raise usefully — it is not the coroutine doing the
    work — so it flags the tracker instead."""
    run = await _running_run(session, task)
    tracker = _tracker(session, task, run, lock=FakeLock(renewable=False), lease=object())
    beater = RunHeartbeat(tracker, session_factory=_factory(session))

    await beater.beat_once()

    with pytest.raises(RunCancelled):
        await tracker.checkpoint()


# -- lifecycle --------------------------------------------------------------


async def test_the_background_loop_beats_repeatedly(
    session: AsyncSession, task: Task
) -> None:
    """The loop keeps beating on its own, not just once when it starts.

    Deliberately waits for observed beats rather than sleeping a fixed
    amount and hoping the event loop scheduled the task. The fixed-sleep
    version of this test failed roughly one run in five under load, and a
    test that fails at random teaches you to ignore failures.
    """
    # Comfortably past the staleness window, so "not stale" at the end can
    # only be the beats — 300 sits exactly on the boundary and raced there.
    run = await _running_run(session, task, age=STALE_AFTER_SECONDS * 2)
    # Beats are counted through the lease, which is a plain integer on the
    # fake. Polling the database instead would mean touching this session
    # from the test while the beater is using it — the concurrent-use
    # hazard SharedSession exists to avoid.
    lock = FakeLock()
    beater = RunHeartbeat(
        _tracker(session, task, run, lock=lock, lease=object()),
        interval_seconds=0.01,
        session_factory=_factory(session),
    )

    async with beater:
        deadline = time.monotonic() + 5.0
        while lock.renewals < 3 and time.monotonic() < deadline:
            await asyncio.sleep(0.01)

    assert lock.renewals >= 3, f"expected repeated beats, observed {lock.renewals}"
    await session.refresh(run)
    assert not is_stale(run, datetime.now(timezone.utc))


async def test_stopping_is_idempotent_and_safe_before_starting(
    session: AsyncSession, task: Task
) -> None:
    run = await _running_run(session, task)
    beater = RunHeartbeat(
        _tracker(session, task, run), session_factory=_factory(session)
    )
    await beater.stop()
    await beater.start()
    await beater.stop()
    await beater.stop()


async def test_a_failing_beat_does_not_kill_the_run_it_protects(
    session: AsyncSession, task: Task
) -> None:
    """Observability must never take down the thing it observes."""
    run = await _running_run(session, task)

    def exploding_session():
        raise RuntimeError("database unavailable")

    beater = RunHeartbeat(
        _tracker(session, task, run),
        interval_seconds=0.01,
        session_factory=exploding_session,
    )
    async with beater:
        await asyncio.sleep(0.05)
    # Surviving the block at all is the assertion: the loop swallowed it.


async def test_the_beat_is_frequent_enough_to_matter() -> None:
    """A schedule where the beat is slower than the reaper is worse than
    none: it would mark healthy runs dead on a timer."""
    assert HEARTBEAT_SECONDS * 4 <= STALE_AFTER_SECONDS
