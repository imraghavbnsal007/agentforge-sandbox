from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.project_analysis import ProjectAnalysis
    from app.models.task import Task


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    repo_path: Mapped[str] = mapped_column(String(500), default="sample_repo")
    # Preferred LLM configuration for new tasks (all optional).
    preferred_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    preferred_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    preferred_execution_profile: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    # GitHub configuration; all null = sample-repo mode.
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    github_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    github_repo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["ProjectAnalysis"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectAnalysis.id"
    )
