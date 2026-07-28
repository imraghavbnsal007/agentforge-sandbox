from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.github_installation import GitHubInstallation


class GitHubInstallationRepository(Base):
    """A repository the installation currently grants access to.

    This table is a *cache* of what GitHub reports, refreshed on demand and
    (from Phase 6E) by webhook. Rows are removed when access is withdrawn, so
    presence here is the authoritative local answer to "may we still touch
    this repository".

    Projects deliberately do not foreign-key into this table — they store
    GitHub's numeric repository id directly — so the cache can be rebuilt
    without cascading into user data.
    """

    __tablename__ = "github_installation_repositories"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "github_repository_id",
            name="uq_installation_repository",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        ForeignKey("github_installations.id", ondelete="CASCADE"), index=True
    )
    github_repository_id: Mapped[int] = mapped_column(BigInteger, index=True)
    owner: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(400), index=True)
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    private: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    installation: Mapped["GitHubInstallation"] = relationship(
        back_populates="repositories"
    )

    @property
    def is_usable(self) -> bool:
        """Archived and disabled repositories cannot receive pull requests."""
        return not self.archived and not self.disabled
