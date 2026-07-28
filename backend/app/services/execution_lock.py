"""Distributed locking and cancellation signalling for task execution.

Two problems this solves that the frontend cannot:

  * **duplicate execution** — nothing previously stopped the same task being
    enqueued twice and run by two workers concurrently, each creating runs and
    each mutating task status. Disabling a button is not a guarantee.
  * **abandoned runs** — a worker that dies mid-run left the task stuck in
    `coding` forever, with no way to tell "still working" from "gone".

A lease, not a lock: the holder renews it while it works, so a crashed worker's
grip expires on its own rather than needing manual clearing. Renewal is
compare-and-extend, so a worker whose lease already lapsed cannot resurrect it
and collide with whoever took over.
"""

import logging
import secrets
from dataclasses import dataclass

from app.core.enums import RunStatus

logger = logging.getLogger(__name__)

EXECUTION_LOCK_PREFIX = "agentforge:lock:task:"
PUBLISH_LOCK_PREFIX = "agentforge:lock:publish:"
CANCEL_PREFIX = "agentforge:cancel:task:"

#: Lease length. Comfortably longer than a heartbeat interval so a busy worker
#: never loses its grip, short enough that a dead one is reclaimed promptly.
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
#: A run whose heartbeat is older than this is treated as abandoned.
STALE_AFTER_SECONDS = 300
#: How long a cancellation request stays pending before it lapses.
CANCEL_TTL_SECONDS = 3600


class LockNotAcquired(Exception):
    """Another worker holds this task. The caller should stand down."""


@dataclass
class Lease:
    key: str
    token: str


class ExecutionLock:
    """One lease per task, for one kind of work."""

    def __init__(self, kv, prefix: str = EXECUTION_LOCK_PREFIX) -> None:
        self._kv = kv
        self._prefix = prefix

    def _key(self, task_id: int) -> str:
        return f"{self._prefix}{task_id}"

    async def acquire(self, task_id: int) -> Lease | None:
        """Take the lease, or return None if someone else holds it.

        The token is random per acquisition so release and renewal can prove
        ownership — without it, a worker could release a lease that had already
        been taken over by another.
        """
        token = secrets.token_urlsafe(16)
        if await self._kv.set_if_absent(self._key(task_id), token, LEASE_SECONDS):
            return Lease(key=self._key(task_id), token=token)
        return None

    async def renew(self, lease: Lease) -> bool:
        """Extend a lease we still hold. False means it lapsed and someone
        else may now own the work — the caller must stop."""
        return await self._kv.compare_and_extend(
            lease.key, lease.token, LEASE_SECONDS
        )

    async def release(self, lease: Lease) -> None:
        await self._kv.compare_and_delete(lease.key, lease.token)

    async def holder(self, task_id: int) -> str | None:
        return await self._kv.get(self._key(task_id))


class CancellationSignal:
    """A user's request to stop, readable by whichever worker holds the task.

    Redis carries the signal for promptness; `AgentRun.cancel_requested_at`
    carries it durably, so a cancellation survives a Redis restart and is still
    honoured at the next checkpoint.
    """

    def __init__(self, kv) -> None:
        self._kv = kv

    def _key(self, task_id: int) -> str:
        return f"{CANCEL_PREFIX}{task_id}"

    async def request(self, task_id: int, user_id: int) -> None:
        await self._kv.set(self._key(task_id), str(user_id), CANCEL_TTL_SECONDS)

    async def is_requested(self, task_id: int) -> bool:
        return await self._kv.get(self._key(task_id)) is not None

    async def clear(self, task_id: int) -> None:
        await self._kv.delete(self._key(task_id))


def is_stale(run, now) -> bool:
    """Whether a running row has lost its worker.

    A run with no heartbeat at all is judged on its start time, which covers a
    worker that died before its first renewal.
    """
    if run.status != RunStatus.running:
        return False
    reference = run.heartbeat_at or run.started_at
    if reference is None:
        return False
    if reference.tzinfo is None:
        from datetime import timezone

        reference = reference.replace(tzinfo=timezone.utc)
    return (now - reference).total_seconds() > STALE_AFTER_SECONDS
