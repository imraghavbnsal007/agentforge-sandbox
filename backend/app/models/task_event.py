from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import RunStage, TaskEventType
from app.db.base import Base, str_enum


class TaskEvent(Base):
    """A durable, ordered record of what happened during a run.

    The live SSE stream is a convenience, **not** the source of truth: a client
    that misses events replays them from this table by sequence number. That is
    why events are persisted before they are published.

    `sequence_number` is monotonic *per run*, which is what makes ordered
    replay after a reconnect possible.

    Nothing credential-bearing is ever stored here — `safe_metadata` is
    scrubbed by TaskEventService before it arrives.
    """

    __tablename__ = "task_events"
    __table_args__ = (
        # Per-run monotonic ordering, enforced rather than assumed.
        UniqueConstraint(
            "run_id", "sequence_number", name="uq_task_event_run_sequence"
        ),
        # The replay query: "everything for this task after cursor N".
        Index("ix_task_events_task_id_id", "task_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Denormalised owner, so the stream can be scoped without a join on the
    # hot path.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, default=0)
    event_type: Mapped[TaskEventType] = mapped_column(str_enum(TaskEventType))
    stage: Mapped[RunStage | None] = mapped_column(
        str_enum(RunStage), nullable=True
    )
    # User-facing text. Never a stack trace, never a raw command.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    safe_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
