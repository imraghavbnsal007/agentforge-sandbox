from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.project_analysis import ProjectAnalysis
    from app.models.task import Task
    from app.models.user import User


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        # Uniqueness is per owner, not global: two users may each register
        # the same repository. This replaced a global UNIQUE(name) in
        # migration 0011.
        UniqueConstraint("user_id", "name", name="uq_projects_user_id_name"),
        # NULL github_repository_id (sample-repo and local PAT projects) does
        # not participate in uniqueness, which is exactly what we want.
        UniqueConstraint(
            "user_id",
            "github_repository_id",
            name="uq_projects_user_id_github_repository_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Owner. Every query that returns projects filters on this.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
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
    # Set only for projects registered through a GitHub App installation.
    # Both stay NULL for sample-repo and AUTH_MODE=local PAT projects, which
    # is what keeps the original single-user workflow legal.
    github_installation_id: Mapped[int | None] = mapped_column(
        ForeignKey("github_installations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # GitHub's numeric repository id — stable across renames, and the key
    # used to re-check that the installation still grants this repository.
    github_repository_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    owner: Mapped["User"] = relationship()
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["ProjectAnalysis"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectAnalysis.id"
    )
