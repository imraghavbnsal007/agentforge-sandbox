from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Integer, JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AgentMode, RunStage, RunStatus
from app.db.base import Base, str_enum

if TYPE_CHECKING:
    from app.models.file_change import FileChange
    from app.models.task import Task
    from app.models.test_result import TestResult


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[AgentMode] = mapped_column(str_enum(AgentMode))
    status: Mapped[RunStatus] = mapped_column(
        str_enum(RunStatus), default=RunStatus.running
    )
    # Fine-grained position within the run; `status` stays the coarse outcome.
    stage: Mapped[RunStage] = mapped_column(
        str_enum(RunStage), default=RunStage.queued
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    # Safe, typed failure reason. The frontend maps this to a message; raw
    # exception text is never shown to a user.
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Renewed by the worker while it holds the run. A stale heartbeat with a
    # running status is how an abandoned run is detected after a crash.
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when a user asks to cancel; the worker stops at its next checkpoint.
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Retry lineage. The previous run is never mutated — a retry creates a new
    # row pointing back at the one it replaces.
    retry_of_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    # Normalised usage, aggregated from llm_runs at the end of the run.
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    plan: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Set when the agent stopped before finishing — out of turns, or going in
    # circles. The run still succeeded and its changes are real; this is the
    # warning that they may not be the whole job. Distinct from `error`, which
    # means the run produced nothing usable.
    incomplete_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Populated when the run is published as a GitHub pull request.
    branch_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    task: Mapped["Task"] = relationship(back_populates="runs")
    file_changes: Mapped[list["FileChange"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="FileChange.id"
    )
    test_results: Mapped[list["TestResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="TestResult.id"
    )
