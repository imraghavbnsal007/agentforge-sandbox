from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AnalysisStatus
from app.db.base import Base, str_enum

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.repo_file_summary import RepoFileSummary
    from app.models.repo_improvement_suggestion import RepoImprovementSuggestion


class ProjectAnalysis(Base):
    __tablename__ = "project_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        str_enum(AnalysisStatus), default=AnalysisStatus.pending
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    languages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    frameworks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    dependencies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    package_manager: Mapped[str | None] = mapped_column(String(50), nullable=True)
    build_command: Mapped[str | None] = mapped_column(String(300), nullable=True)
    test_command: Mapped[str | None] = mapped_column(String(300), nullable=True)
    architecture_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_areas: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    entry_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    api_routes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    repo_map: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sql_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    schema_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    health_score: Mapped[int | None] = mapped_column(nullable=True)
    health_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="analyses")
    file_summaries: Mapped[list["RepoFileSummary"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="RepoFileSummary.importance_score.desc()",
    )
    suggestions: Mapped[list["RepoImprovementSuggestion"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="RepoImprovementSuggestion.id",
    )
