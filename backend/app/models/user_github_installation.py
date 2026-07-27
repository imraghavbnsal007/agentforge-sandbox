from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.github_installation import GitHubInstallation
    from app.models.user import User


class UserGitHubInstallation(Base):
    """Records that a user was verified to have access to an installation.

    The link is only ever created after GitHub itself confirmed the
    installation appears in that user's own `GET /user/installations` list,
    so it cannot be forged by posting an installation id.

    `verified_at` is when that confirmation last happened — a link is
    evidence of past verification, not a standing capability. Repository
    operations re-check installation state at execution time.
    """

    __tablename__ = "user_github_installations"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "installation_id", name="uq_user_github_installation"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    installation_id: Mapped[int] = mapped_column(
        ForeignKey("github_installations.id", ondelete="CASCADE"), index=True
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship()
    installation: Mapped["GitHubInstallation"] = relationship(
        back_populates="user_links"
    )
