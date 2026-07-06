from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AgentMode, RunStatus
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
    plan: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    log: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
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
