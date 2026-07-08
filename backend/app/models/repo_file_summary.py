from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.project_analysis import ProjectAnalysis


class RepoFileSummary(Base):
    __tablename__ = "repo_file_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("project_analyses.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(50), default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    importance_score: Mapped[int] = mapped_column(Integer, default=0)

    analysis: Mapped["ProjectAnalysis"] = relationship(back_populates="file_summaries")
