"""Recording and broadcasting task execution events.

Order matters: an event is **persisted before it is published**. The Redis
channel is a delivery convenience; PostgreSQL is the source of truth. A client
that misses a live event replays it from `task_events` by cursor, so a dropped
connection costs nothing.

Everything published is scrubbed. `SAFE_METADATA_KEYS` is an allowlist, not a
blocklist — a new field is invisible until someone deliberately admits it,
which is the right default when the alternative is leaking a token.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RunStage, TaskEventType
from app.models import AgentRun, Project, Task, TaskEvent
from app.services.github_app_api import redact_secrets

logger = logging.getLogger(__name__)

EVENT_CHANNEL_PREFIX = "agentforge:events:task:"

#: Only these keys ever reach a client. Anything else is dropped silently.
SAFE_METADATA_KEYS = frozenset(
    {
        "provider",
        "model",
        "profile",
        "tool",
        "suite",
        "passed",
        "failed",
        "errored",
        "duration",
        "duration_ms",
        "path",
        "change_type",
        "files_changed",
        "branch",
        "commit_sha",
        "pr_url",
        "tokens_in",
        "tokens_out",
        "cached_tokens",
        "cost_usd",
        "model_calls",
        "tool_calls",
        "attempt",
        "reason",
    }
)

#: Never emitted, whatever a caller passes.
_FORBIDDEN_KEYS = frozenset(
    {
        "token",
        "access_token",
        "installation_token",
        "authorization",
        "secret",
        "password",
        "private_key",
        "api_key",
        "prompt",
        "messages",
        "diff",
        "content",
        "env",
        "environ",
        "command",
        "argv",
    }
)


def channel_for(task_id: int) -> str:
    return f"{EVENT_CHANNEL_PREFIX}{task_id}"


def scrub_metadata(raw: dict | None) -> dict:
    """Allowlist, then redact anything token-shaped that slipped through."""
    if not raw:
        return {}
    safe: dict = {}
    for key, value in raw.items():
        lowered = key.lower()
        if lowered in _FORBIDDEN_KEYS or lowered not in SAFE_METADATA_KEYS:
            continue
        if isinstance(value, str):
            value = redact_secrets(value)
        safe[key] = value
    return safe


def scrub_message(message: str | None) -> str | None:
    """Messages are user-facing: redact secrets and cap the length.

    A stack trace or a full command line must never arrive here — callers pass
    a human sentence and put diagnostics in the log instead.
    """
    if message is None:
        return None
    return redact_secrets(message)[:1000]


@dataclass
class EventPayload:
    """What a subscriber receives. Mirrors the persisted row."""

    id: int
    task_id: int
    run_id: int | None
    sequence_number: int
    event_type: str
    stage: str | None = None
    message: str | None = None
    progress: int | None = None
    error_code: str | None = None
    safe_metadata: dict = field(default_factory=dict)
    created_at: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "task_id": self.task_id,
                "run_id": self.run_id,
                "sequence_number": self.sequence_number,
                "event_type": self.event_type,
                "stage": self.stage,
                "message": self.message,
                "progress": self.progress,
                "error_code": self.error_code,
                "metadata": self.safe_metadata,
                "created_at": self.created_at,
            }
        )


class TaskEventService:
    def __init__(self, session: AsyncSession, kv=None) -> None:
        self.session = session
        self._kv = kv

    async def _next_sequence(self, run_id: int | None) -> int:
        """Per-run monotonic counter. Runs are single-writer (one worker holds
        the lock), so a max+1 read is sufficient here."""
        if run_id is None:
            return 0
        current = (
            await self.session.execute(
                select(func.coalesce(func.max(TaskEvent.sequence_number), 0)).where(
                    TaskEvent.run_id == run_id
                )
            )
        ).scalar_one()
        return int(current) + 1

    async def emit(
        self,
        task: Task,
        event_type: TaskEventType,
        *,
        run: AgentRun | None = None,
        user_id: int | None = None,
        stage: RunStage | None = None,
        message: str | None = None,
        progress: int | None = None,
        error_code: str | None = None,
        metadata: dict | None = None,
    ) -> TaskEvent:
        """Persist an event, then publish it. Never raises into the caller.

        A failure to broadcast must not fail the run it is describing — the
        event is already durable, and the client will pick it up on replay.
        """
        if user_id is None:
            project = await self.session.get(Project, task.project_id)
            user_id = project.user_id if project else 0

        event = TaskEvent(
            task_id=task.id,
            run_id=run.id if run else None,
            user_id=user_id,
            sequence_number=await self._next_sequence(run.id if run else None),
            event_type=event_type,
            stage=stage,
            message=scrub_message(message),
            progress=progress,
            error_code=error_code,
            safe_metadata=scrub_metadata(metadata) or None,
        )
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)

        await self._publish(event)
        return event

    async def _publish(self, event: TaskEvent) -> None:
        if self._kv is None:
            return
        payload = EventPayload(
            id=event.id,
            task_id=event.task_id,
            run_id=event.run_id,
            sequence_number=event.sequence_number,
            event_type=str(event.event_type),
            stage=str(event.stage) if event.stage else None,
            message=event.message,
            progress=event.progress,
            error_code=event.error_code,
            safe_metadata=event.safe_metadata or {},
            created_at=(event.created_at or datetime.now(timezone.utc)).isoformat(),
        )
        try:
            await self._kv.publish(channel_for(event.task_id), payload.to_json())
        except Exception:
            # Broadcast is best-effort; the row is already durable.
            logger.warning(
                "Could not publish event %s for task %s", event.id, event.task_id
            )

    async def history(
        self, task_id: int, after_id: int = 0, limit: int = 500
    ) -> list[TaskEvent]:
        """Ordered replay after a cursor — how a reconnecting client catches up."""
        result = await self.session.execute(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.id > after_id)
            .order_by(TaskEvent.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def prune(self, keep_days: int = 30) -> int:
        """Bounded retention. Events are diagnostics, not history — the run
        row keeps the durable outcome."""
        from datetime import timedelta

        from sqlalchemy import delete

        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        result = await self.session.execute(
            delete(TaskEvent).where(TaskEvent.created_at < cutoff),
            # Let the database do the comparison. Evaluating it in Python
            # trips over SQLite storing naive datetimes where Postgres stores
            # timezone-aware ones.
            execution_options={"synchronize_session": False},
        )
        await self.session.commit()
        return result.rowcount or 0
