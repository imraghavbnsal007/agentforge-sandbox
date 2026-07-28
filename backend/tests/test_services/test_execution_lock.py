"""Distributed locking, cancellation signalling and stale-run detection.

Before Phase 7 nothing stopped the same task being executed by two workers
concurrently. These tests pin down the guarantee that now does.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.enums import RunStatus
from app.models import AgentRun
from app.services.execution_lock import (
    PUBLISH_LOCK_PREFIX,
    STALE_AFTER_SECONDS,
    CancellationSignal,
    ExecutionLock,
    is_stale,
)
from app.services.kv_store import InMemoryKVStore


# -- mutual exclusion -------------------------------------------------------


async def test_only_one_worker_can_hold_a_task(kv: InMemoryKVStore):
    lock = ExecutionLock(kv)
    first = await lock.acquire(42)
    second = await lock.acquire(42)

    assert first is not None
    assert second is None, "a second worker must not get the same task"


async def test_releasing_lets_the_next_worker_in(kv: InMemoryKVStore):
    lock = ExecutionLock(kv)
    lease = await lock.acquire(42)
    await lock.release(lease)
    assert await lock.acquire(42) is not None


async def test_different_tasks_do_not_block_each_other(kv: InMemoryKVStore):
    lock = ExecutionLock(kv)
    assert await lock.acquire(1) is not None
    assert await lock.acquire(2) is not None


async def test_execution_and_publish_locks_are_independent(kv: InMemoryKVStore):
    """A task may be publishing while a different concern holds its own lock."""
    execution = ExecutionLock(kv)
    publish = ExecutionLock(kv, prefix=PUBLISH_LOCK_PREFIX)
    assert await execution.acquire(7) is not None
    assert await publish.acquire(7) is not None


# -- ownership --------------------------------------------------------------


async def test_a_worker_cannot_release_a_lease_it_no_longer_owns(
    kv: InMemoryKVStore,
):
    """The token is what stops one worker unlocking another's work."""
    lock = ExecutionLock(kv)
    original = await lock.acquire(42)

    # Simulate the lease expiring and another worker taking over.
    await kv.delete(original.key)
    successor = await lock.acquire(42)

    await lock.release(original)  # the old holder tries to clean up
    # The successor still holds it.
    assert await lock.holder(42) == successor.token


async def test_renewing_extends_a_lease_we_still_hold(kv: InMemoryKVStore):
    lock = ExecutionLock(kv)
    lease = await lock.acquire(42)
    assert await lock.renew(lease) is True


async def test_renewing_a_lapsed_lease_fails(kv: InMemoryKVStore):
    """A worker whose lease expired must not resurrect it and collide with
    whoever took over."""
    lock = ExecutionLock(kv)
    lease = await lock.acquire(42)
    await kv.delete(lease.key)
    await lock.acquire(42)  # someone else takes it

    assert await lock.renew(lease) is False


async def test_each_acquisition_gets_a_distinct_token(kv: InMemoryKVStore):
    lock = ExecutionLock(kv)
    first = await lock.acquire(1)
    await lock.release(first)
    second = await lock.acquire(1)
    assert first.token != second.token


# -- cancellation signalling ------------------------------------------------


async def test_cancellation_can_be_requested_and_read(kv: InMemoryKVStore):
    signal = CancellationSignal(kv)
    assert await signal.is_requested(5) is False
    await signal.request(5, user_id=1)
    assert await signal.is_requested(5) is True


async def test_clearing_a_cancellation_removes_it(kv: InMemoryKVStore):
    signal = CancellationSignal(kv)
    await signal.request(5, user_id=1)
    await signal.clear(5)
    assert await signal.is_requested(5) is False


async def test_cancellations_are_per_task(kv: InMemoryKVStore):
    signal = CancellationSignal(kv)
    await signal.request(5, user_id=1)
    assert await signal.is_requested(6) is False


# -- stale run detection ----------------------------------------------------


def _run(status: RunStatus, heartbeat_age: int | None) -> AgentRun:
    now = datetime.now(timezone.utc)
    return AgentRun(
        task_id=1,
        mode="mock",
        status=status,
        started_at=now - timedelta(seconds=heartbeat_age or 0),
        heartbeat_at=(
            now - timedelta(seconds=heartbeat_age)
            if heartbeat_age is not None
            else None
        ),
    )


def test_a_fresh_heartbeat_is_not_stale():
    assert is_stale(_run(RunStatus.running, 10), datetime.now(timezone.utc)) is False


def test_an_old_heartbeat_is_stale():
    """This is how a crashed worker's run is detected."""
    run = _run(RunStatus.running, STALE_AFTER_SECONDS + 60)
    assert is_stale(run, datetime.now(timezone.utc)) is True


def test_a_run_that_never_beat_falls_back_to_its_start_time():
    """Covers a worker that died before its first renewal."""
    run = _run(RunStatus.running, None)
    run.started_at = datetime.now(timezone.utc) - timedelta(
        seconds=STALE_AFTER_SECONDS + 60
    )
    assert is_stale(run, datetime.now(timezone.utc)) is True


@pytest.mark.parametrize(
    "status",
    [RunStatus.completed, RunStatus.failed, RunStatus.cancelled,
     RunStatus.abandoned],
)
def test_a_finished_run_is_never_stale(status):
    """Only a *running* row can have lost its worker."""
    run = _run(status, STALE_AFTER_SECONDS + 600)
    assert is_stale(run, datetime.now(timezone.utc)) is False


def test_a_naive_timestamp_is_handled():
    """SQLite hands back naive datetimes; comparison must not explode."""
    run = _run(RunStatus.running, None)
    run.heartbeat_at = datetime.now() - timedelta(seconds=STALE_AFTER_SECONDS + 60)
    assert is_stale(run, datetime.now(timezone.utc)) is True
