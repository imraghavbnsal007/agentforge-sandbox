"""Event recording, scrubbing, ordering and replay."""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RunStage, TaskEventType
from app.models import AgentRun, Task
from app.services.kv_store import InMemoryKVStore
from app.services.task_events import (
    TaskEventService,
    channel_for,
    scrub_message,
    scrub_metadata,
)

TOKEN = "ghs_installation_token_should_never_appear"


@pytest.fixture
async def run(session: AsyncSession, task: Task) -> AgentRun:
    run = AgentRun(task_id=task.id, mode="mock", file_changes=[], test_results=[])
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


# -- scrubbing --------------------------------------------------------------


def test_metadata_is_an_allowlist_not_a_blocklist():
    """A field nobody deliberately admitted must not appear."""
    safe = scrub_metadata(
        {"provider": "google", "surprise_new_field": "leak", "token": TOKEN}
    )
    assert safe == {"provider": "google"}


@pytest.mark.parametrize(
    "key",
    ["token", "access_token", "authorization", "private_key", "prompt",
     "diff", "command", "env"],
)
def test_forbidden_keys_never_survive(key: str):
    assert scrub_metadata({key: "sensitive"}) == {}


def test_token_shaped_values_are_redacted_even_on_allowed_keys():
    safe = scrub_metadata({"reason": f"failed with {TOKEN}"})
    assert TOKEN not in safe["reason"]


def test_messages_are_redacted_and_bounded():
    assert TOKEN not in scrub_message(f"boom {TOKEN}")
    assert len(scrub_message("x" * 5000)) == 1000
    assert scrub_message(None) is None


def test_empty_metadata_is_empty():
    assert scrub_metadata(None) == {}
    assert scrub_metadata({}) == {}


# -- persistence and ordering ----------------------------------------------


async def test_events_get_monotonic_per_run_sequence_numbers(
    session: AsyncSession, task: Task, run: AgentRun, kv: InMemoryKVStore
):
    service = TaskEventService(session, kv)
    for stage in (RunStage.preparing, RunStage.cloning, RunStage.planning):
        await service.emit(
            task, TaskEventType.stage_changed, run=run, stage=stage, user_id=1
        )
    history = await service.history(task.id)
    assert [e.sequence_number for e in history] == [1, 2, 3]


async def test_history_replays_in_order_after_a_cursor(
    session: AsyncSession, task: Task, run: AgentRun, kv: InMemoryKVStore
):
    service = TaskEventService(session, kv)
    created = [
        await service.emit(
            task, TaskEventType.stage_changed, run=run, message=f"m{i}", user_id=1
        )
        for i in range(5)
    ]
    after = await service.history(task.id, after_id=created[1].id)
    assert [e.message for e in after] == ["m2", "m3", "m4"]


async def test_history_is_bounded_by_limit(
    session: AsyncSession, task: Task, run: AgentRun, kv: InMemoryKVStore
):
    service = TaskEventService(session, kv)
    for i in range(10):
        await service.emit(task, TaskEventType.progress, run=run, user_id=1)
    assert len(await service.history(task.id, limit=4)) == 4


async def test_events_are_published_to_the_task_channel(
    session: AsyncSession, task: Task, run: AgentRun, kv: InMemoryKVStore
):
    service = TaskEventService(session, kv)
    await service.emit(
        task,
        TaskEventType.stage_changed,
        run=run,
        stage=RunStage.cloning,
        message="Cloning repository",
        progress=10,
        user_id=1,
    )
    published = kv.published[channel_for(task.id)]
    assert len(published) == 1
    payload = json.loads(published[0])
    assert payload["event_type"] == "stage_changed"
    assert payload["stage"] == "cloning"
    assert payload["progress"] == 10


async def test_a_publish_failure_does_not_sink_the_event(
    session: AsyncSession, task: Task, run: AgentRun
):
    """Observability must never take down the thing it observes."""

    class BrokenKV(InMemoryKVStore):
        async def publish(self, channel, message):
            raise ConnectionError("redis down")

    service = TaskEventService(session, BrokenKV())
    event = await service.emit(task, TaskEventType.warning, run=run, user_id=1)
    # Durable even though the broadcast failed.
    assert event.id is not None
    assert len(await service.history(task.id)) == 1


async def test_no_token_reaches_the_stored_row_or_the_channel(
    session: AsyncSession, task: Task, run: AgentRun, kv: InMemoryKVStore
):
    service = TaskEventService(session, kv)
    await service.emit(
        task,
        TaskEventType.warning,
        run=run,
        user_id=1,
        message=f"clone failed using {TOKEN}",
        metadata={"token": TOKEN, "provider": "google"},
    )
    stored = (await service.history(task.id))[0]
    assert TOKEN not in (stored.message or "")
    assert TOKEN not in json.dumps(stored.safe_metadata or {})
    assert TOKEN not in json.dumps(kv.published)


async def test_events_without_a_run_are_allowed(
    session: AsyncSession, task: Task, kv: InMemoryKVStore
):
    """Task-level events (queued, cancelled-before-start) have no run."""
    service = TaskEventService(session, kv)
    event = await service.emit(task, TaskEventType.task_queued, user_id=1)
    assert event.run_id is None
    assert event.sequence_number == 0


# -- retention --------------------------------------------------------------


async def test_prune_removes_only_old_events(
    session: AsyncSession, task: Task, run: AgentRun, kv: InMemoryKVStore
):
    from datetime import datetime, timedelta, timezone

    service = TaskEventService(session, kv)
    recent = await service.emit(task, TaskEventType.progress, run=run, user_id=1)
    old = await service.emit(task, TaskEventType.progress, run=run, user_id=1)
    old.created_at = datetime.now(timezone.utc) - timedelta(days=90)
    await session.commit()

    removed = await service.prune(keep_days=30)
    assert removed == 1
    remaining = await service.history(task.id)
    assert [e.id for e in remaining] == [recent.id]
