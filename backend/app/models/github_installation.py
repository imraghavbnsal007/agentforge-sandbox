from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.github_installation_repository import (
        GitHubInstallationRepository,
    )
    from app.models.user_github_installation import UserGitHubInstallation

# GitHub's own vocabulary, mirrored so comparisons read the same as the API.
ACCOUNT_TYPE_USER = "User"
ACCOUNT_TYPE_ORGANIZATION = "Organization"
SELECTION_ALL = "all"
SELECTION_SELECTED = "selected"


class GitHubInstallation(Base):
    """One installation of the AgentForge GitHub App on a user or org account.

    This row records *what GitHub told us* about the installation. It never
    holds an installation access token — those are short-lived, minted on
    demand, and cached only in Redis.
    """

    __tablename__ = "github_installations"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_installation_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True
    )
    # The account the App is installed on.
    account_id: Mapped[int] = mapped_column(BigInteger)
    account_login: Mapped[str] = mapped_column(String(200), index=True)
    account_type: Mapped[str] = mapped_column(String(40), default=ACCOUNT_TYPE_USER)
    target_type: Mapped[str] = mapped_column(String(40), default=ACCOUNT_TYPE_USER)
    # "all" or "selected" — whether the user granted every repository.
    repository_selection: Mapped[str] = mapped_column(
        String(20), default=SELECTION_SELECTED
    )
    # Set while GitHub reports the installation suspended; cleared on unsuspend.
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when the installation is removed. The row is kept so historical
    # tasks and analyses stay attributable — access is what gets revoked,
    # never the history.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user_links: Mapped[list["UserGitHubInstallation"]] = relationship(
        back_populates="installation", cascade="all, delete-orphan"
    )
    repositories: Mapped[list["GitHubInstallationRepository"]] = relationship(
        back_populates="installation", cascade="all, delete-orphan"
    )

    @property
    def is_suspended(self) -> bool:
        return self.suspended_at is not None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_active(self) -> bool:
        """Whether repository operations may use this installation."""
        return not self.is_suspended and not self.is_revoked

    @property
    def account_slug(self) -> str:
        return self.account_login
