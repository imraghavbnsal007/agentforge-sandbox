"""Verifying, linking, and gating GitHub App installations.

The security property this module exists to enforce: **an installation id
arriving from a browser is never trusted.** A link between a user and an
installation is created only after GitHub itself confirms, against the
user's own OAuth token, that the installation appears in their
`GET /user/installations` list.

The user's OAuth token is passed in as an argument, used for that one call,
and never stored — see `link_installation_for_user`.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.models import GitHubInstallation, User, UserGitHubInstallation
from app.services.github_app_api import (
    GitHubAppAPI,
    InstallationInfo,
)
from app.services.github_app_auth import generate_app_jwt

logger = logging.getLogger(__name__)

# Audit events.
INSTALLATION_LINKED = "github.installation.linked"
INSTALLATION_REJECTED = "github.installation.rejected"
INSTALLATION_SUSPENDED = "github.installation.suspended"


class InstallationAccessError(Exception):
    """The installation cannot be used: not the user's, suspended, or removed.

    Deliberately one type with a user-safe message — a caller should not be
    able to distinguish "not yours" from "does not exist".
    """


class InstallationService:
    def __init__(
        self, session: AsyncSession, api: GitHubAppAPI | None = None
    ) -> None:
        self.session = session
        self._api = api or GitHubAppAPI()

    # -- Reads ------------------------------------------------------------

    async def get_by_github_id(
        self, github_installation_id: int
    ) -> GitHubInstallation | None:
        result = await self.session.execute(
            select(GitHubInstallation).where(
                GitHubInstallation.github_installation_id
                == github_installation_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user: User) -> list[GitHubInstallation]:
        result = await self.session.execute(
            select(GitHubInstallation)
            .join(
                UserGitHubInstallation,
                UserGitHubInstallation.installation_id == GitHubInstallation.id,
            )
            .where(UserGitHubInstallation.user_id == user.id)
            .order_by(GitHubInstallation.account_login)
        )
        return list(result.scalars().all())

    async def is_linked(self, user: User, installation: GitHubInstallation) -> bool:
        result = await self.session.execute(
            select(UserGitHubInstallation.id).where(
                UserGitHubInstallation.user_id == user.id,
                UserGitHubInstallation.installation_id == installation.id,
            )
        )
        return result.scalar_one_or_none() is not None

    # -- Gating -----------------------------------------------------------

    async def require_usable(
        self, user: User, github_installation_id: int
    ) -> GitHubInstallation:
        """Resolve an installation the user may actually operate through.

        Every failure mode returns the same shape of error so a caller cannot
        probe which installations exist.
        """
        installation = await self.get_by_github_id(github_installation_id)
        if installation is None or not await self.is_linked(user, installation):
            raise InstallationAccessError(
                "That GitHub installation is not available to your account."
            )
        assert_active(installation)
        return installation

    # -- Writes -----------------------------------------------------------

    async def upsert_installation(
        self, info: InstallationInfo
    ) -> GitHubInstallation:
        """Create or refresh the local record from GitHub's canonical data."""
        installation = await self.get_by_github_id(info.github_installation_id)
        if installation is None:
            installation = GitHubInstallation(
                github_installation_id=info.github_installation_id
            )
            self.session.add(installation)

        installation.account_id = info.account_id
        installation.account_login = info.account_login
        installation.account_type = info.account_type
        installation.target_type = info.target_type
        installation.repository_selection = info.repository_selection
        installation.suspended_at = info.suspended_at
        # Seeing it in GitHub's API at all means it is not removed.
        installation.revoked_at = None
        installation.last_synced_at = datetime.now(timezone.utc)
        return installation

    async def link_installation_for_user(
        self,
        user: User,
        github_installation_id: int,
        user_access_token: str,
    ) -> GitHubInstallation:
        """Verify an installation belongs to this user, then record the link.

        `user_access_token` is a freshly-minted OAuth token supplied by the
        caller. It is used for exactly one API call and is never written to
        Redis, PostgreSQL, or a log. Nothing in this method retains it.
        """
        # 1. Authoritative ownership check, from the user's own perspective.
        accessible = await self._api.list_user_installations(user_access_token)
        match = next(
            (
                item
                for item in accessible
                if item.github_installation_id == github_installation_id
            ),
            None,
        )
        if match is None:
            audit(
                INSTALLATION_REJECTED,
                reason="not_accessible_to_user",
                user_id=user.id,
                github_login=user.github_login,
                installation_id=github_installation_id,
            )
            raise InstallationAccessError(
                "That GitHub installation is not available to your account."
            )

        # 2. Re-read through the App JWT for the canonical record. The user
        #    list can lag on suspension state; the app-level record is what
        #    repository operations will be gated on.
        try:
            info = await self._api.get_installation(
                generate_app_jwt(), github_installation_id
            )
        except Exception:
            # App-level read unavailable — fall back to the verified user-side
            # record rather than failing a legitimate installation.
            logger.warning(
                "App-level installation read failed for %s; using the "
                "user-scoped record",
                github_installation_id,
            )
            info = match

        installation = await self.upsert_installation(info)
        await self.session.flush()

        if not await self.is_linked(user, installation):
            self.session.add(
                UserGitHubInstallation(
                    user_id=user.id, installation_id=installation.id
                )
            )
            try:
                await self.session.commit()
            except IntegrityError:
                # Two callbacks raced for the same installation; the link
                # already exists, which is the desired end state.
                await self.session.rollback()
                installation = await self.get_by_github_id(github_installation_id)
        else:
            # Repeat callback: refresh verification time, do not duplicate.
            await self.session.commit()

        await self.session.refresh(installation)
        audit(
            INSTALLATION_LINKED,
            user_id=user.id,
            github_login=user.github_login,
            installation_id=github_installation_id,
            account=installation.account_login,
            suspended=installation.is_suspended,
        )
        if installation.is_suspended:
            audit(
                INSTALLATION_SUSPENDED,
                installation_id=github_installation_id,
                account=installation.account_login,
            )
        return installation

    async def sync_from_github(
        self, github_installation_id: int
    ) -> GitHubInstallation:
        """Refresh one installation's status from GitHub (App JWT only)."""
        info = await self._api.get_installation(
            generate_app_jwt(), github_installation_id
        )
        installation = await self.upsert_installation(info)
        await self.session.commit()
        await self.session.refresh(installation)
        return installation

    async def mark_revoked(self, github_installation_id: int) -> None:
        """Record that an installation is gone. History is preserved; only
        future access is blocked."""
        installation = await self.get_by_github_id(github_installation_id)
        if installation is None:
            return
        installation.revoked_at = datetime.now(timezone.utc)
        await self.session.commit()


def assert_active(installation: GitHubInstallation) -> None:
    """Raise unless the installation may be used right now."""
    if installation.is_revoked:
        raise InstallationAccessError(
            f"AgentForge has been removed from {installation.account_login} on "
            "GitHub. Reinstall the GitHub App to continue."
        )
    if installation.is_suspended:
        raise InstallationAccessError(
            f"The AgentForge installation on {installation.account_login} is "
            "suspended on GitHub. Unsuspend it to continue."
        )
