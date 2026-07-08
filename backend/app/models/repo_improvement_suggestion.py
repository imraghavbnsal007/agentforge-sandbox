from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.project_analysis import ProjectAnalysis


class RepoImprovementSuggestion(Base):
    __tablename__ = "repo_improvement_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("project_analyses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), default="quality")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    related_files: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default="medium")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    effort: Mapped[str] = mapped_column(String(20), default="medium")

    analysis: Mapped["ProjectAnalysis"] = relationship(back_populates="suggestions")
