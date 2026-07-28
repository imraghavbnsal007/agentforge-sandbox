"""Server-sent event streaming for task execution.

SSE rather than WebSockets: the traffic is one-directional, it rides on plain
HTTP so the existing session cookie authenticates it unchanged, and browsers
reconnect and resend `Last-Event-ID` on their own. A WebSocket would mean a
second auth path and a hand-written reconnect loop for no benefit.

**Replay first, then follow.** On connect, everything after the client's cursor
is sent from PostgreSQL; only then does the stream switch to live messages.
That is what makes a dropped connection lossless — the live channel is a
delivery convenience, never the source of truth.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from app.core.enums import TaskEventType
from app.services.task_events import EventPayload, channel_for

logger = logging.getLogger(__name__)

#: Comment frames keep proxies from closing an idle connection. Well under the
#: usual 60s idle timeout.
HEARTBEAT_SECONDS = 20
#: How long to wait for a live message before emitting a heartbeat.
POLL_TIMEOUT_SECONDS = 1.0


def format_sse(data: str, event: str | None = None, event_id: int | None = None) -> str:
    """One SSE frame. `id:` is what the browser echoes back on reconnect."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event:
        lines.append(f"event: {event}")
    for line in data.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def heartbeat_frame() -> str:
    """A comment frame: keeps the connection warm, ignored by EventSource."""
    return ": heartbeat\n\n"


async def task_event_stream(
    task_id: int,
    events,
    kv,
    after_id: int = 0,
    request=None,
) -> AsyncIterator[str]:
    """Replay missed events, then follow the live channel."""
    cursor = after_id

    # -- 1. Replay from the durable log -----------------------------------
    try:
        for record in await events.history(task_id, after_id=cursor):
            payload = EventPayload(
                id=record.id,
                task_id=record.task_id,
                run_id=record.run_id,
                sequence_number=record.sequence_number,
                event_type=str(record.event_type),
                stage=str(record.stage) if record.stage else None,
                message=record.message,
                progress=record.progress,
                error_code=record.error_code,
                safe_metadata=record.safe_metadata or {},
                created_at=record.created_at.isoformat() if record.created_at else "",
            )
            cursor = record.id
            yield format_sse(payload.to_json(), event=payload.event_type, event_id=cursor)
    except Exception:
        logger.warning("Could not replay events for task %s", task_id)

    # -- 2. Follow the live channel ---------------------------------------
    subscription = None
    try:
        subscription = await _subscribe(kv, channel_for(task_id))
    except Exception:
        # No live channel (Redis down, or an in-memory store in tests). The
        # client still has the replayed history and its polling fallback.
        logger.info("Live channel unavailable for task %s; replay only", task_id)

    if subscription is None:
        yield format_sse(
            '{"event_type":"stream_degraded"}', event="stream_degraded"
        )
        return

    since_heartbeat = 0.0
    try:
        while True:
            if request is not None and await request.is_disconnected():
                break
            message = await _next_message(subscription)
            if message is None:
                since_heartbeat += POLL_TIMEOUT_SECONDS
                if since_heartbeat >= HEARTBEAT_SECONDS:
                    since_heartbeat = 0.0
                    yield heartbeat_frame()
                continue
            since_heartbeat = 0.0
            event_id = _event_id_of(message)
            # Drop anything already replayed, so a race between replay and
            # subscribe cannot deliver an event twice.
            if event_id is not None and event_id <= cursor:
                continue
            if event_id is not None:
                cursor = event_id
            yield format_sse(
                message, event=_event_type_of(message), event_id=event_id
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Event stream for task %s ended unexpectedly", task_id)
    finally:
        await _unsubscribe(subscription)


# -- transport helpers ------------------------------------------------------
#
# Kept small and separate so an in-memory store can stand in for Redis
# without the streaming logic knowing the difference.


async def _subscribe(kv, channel: str):
    client = getattr(kv, "_client", None)
    if client is None:
        return None
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    return pubsub


async def _next_message(subscription) -> str | None:
    try:
        message = await subscription.get_message(
            ignore_subscribe_messages=True, timeout=POLL_TIMEOUT_SECONDS
        )
    except Exception:
        return None
    if not message:
        return None
    data = message.get("data")
    if isinstance(data, bytes):
        return data.decode()
    return str(data) if data is not None else None


async def _unsubscribe(subscription) -> None:
    if subscription is None:
        return
    try:
        await subscription.unsubscribe()
        await subscription.aclose()
    except Exception:
        pass


def _event_id_of(raw: str) -> int | None:
    import json

    try:
        return int(json.loads(raw).get("id"))
    except (ValueError, TypeError, AttributeError):
        return None


def _event_type_of(raw: str) -> str:
    import json

    try:
        return str(json.loads(raw).get("event_type") or TaskEventType.stage_changed)
    except (ValueError, TypeError, AttributeError):
        return str(TaskEventType.stage_changed)
