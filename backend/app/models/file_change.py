from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ChangeType
from app.db.base import Base, str_enum

if TYPE_CHECKING:
    from app.models.agent_run import AgentRun


class FileChange(Base):
    __tablename__ = "file_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(500))
    change_type: Mapped[ChangeType] = mapped_column(str_enum(ChangeType))
    diff: Mapped[str] = mapped_column(Text, default="")

    run: Mapped["AgentRun"] = relationship(back_populates="file_changes")
