"""Applying GitHub webhook events to local installation state.

Every handler is idempotent — upserts and set-to-value operations, never
increments — so a redelivery, or a replay after the dedup ledger is lost,
converges on the same state rather than compounding.

Nothing here trusts the payload for authorisation. A webhook can only change
*cached* state: which installations are suspended or revoked, and which
repositories are granted. Whether an operation may proceed is still decided
at execution time by GitHubCredentialResolver.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import (
    INSTALLATION_REVOKED,
    INSTALLATION_UNSUSPENDED,
    REPOSITORIES_ADDED,
    REPOSITORIES_REMOVED,
    audit,
)
from app.models import GitHubInstallation, GitHubInstallationRepository
from app.services.github_app_api import parse_installation, parse_repository
from app.services.installation_service import (
    INSTALLATION_SUSPENDED,
    InstallationService,
)

logger = logging.getLogger(__name__)

EVENT_INSTALLATION = "installation"
EVENT_INSTALLATION_REPOSITORIES = "installation_repositories"
EVENT_PING = "ping"

# Actions we act on. Anything else is recorded and ignored.
INSTALLATION_ACTIONS = {
    "created",
    "deleted",
    "suspend",
    "unsuspend",
    "new_permissions_accepted",
}
REPOSITORY_ACTIONS = {"added", "removed"}

SUPPORTED_EVENTS = {
    EVENT_PING,
    EVENT_INSTALLATION,
    EVENT_INSTALLATION_REPOSITORIES,
}


def installation_id_from(payload: dict) -> int | None:
    """The installation this delivery concerns, if any."""
    raw = (payload.get("installation") or {}).get("id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


class WebhookHandler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.installations = InstallationService(session)

    async def handle(self, event: str, payload: dict) -> bool:
        """Apply one delivery. Returns True when it changed local state.

        An unsupported event or action is not an error — GitHub may send
        events we do not subscribe to, and answering non-2xx would make it
        retry something we will never handle.
        """
        if event == EVENT_PING:
            return False
        if event == EVENT_INSTALLATION:
            return await self._handle_installation(payload)
        if event == EVENT_INSTALLATION_REPOSITORIES:
            return await self._handle_repositories(payload)
        return False

    # -- installation ------------------------------------------------------

    async def _handle_installation(self, payload: dict) -> bool:
        action = str(payload.get("action") or "")
        if action not in INSTALLATION_ACTIONS:
            return False

        raw = payload.get("installation") or {}
        github_installation_id = installation_id_from(payload)
        if github_installation_id is None:
            return False

        if action == "deleted":
            return await self._revoke(github_installation_id)
        if action == "suspend":
            return await self._set_suspended(github_installation_id, True)
        if action == "unsuspend":
            return await self._set_suspended(github_installation_id, False)

        # created / new_permissions_accepted -> upsert from the payload.
        info = parse_installation(raw)
        installation = await self.installations.upsert_installation(info)
        await self.session.flush()

        # `created` carries the initial repository grant; seed the cache so
        # the picker is populated without waiting for a manual refresh.
        repositories = payload.get("repositories")
        if action == "created" and isinstance(repositories, list):
            await self._replace_repositories(installation, repositories)

        await self.session.commit()
        logger.info(
            "Installation %s upserted from webhook (%s)",
            github_installation_id,
            action,
        )
        return True

    async def _revoke(self, github_installation_id: int) -> bool:
        """Mark the installation gone and drop its repository grants.

        The installation row itself is retained so historical tasks, runs and
        analyses stay attributable — only access is withdrawn.
        """
        installation = await self.installations.get_by_github_id(
            github_installation_id
        )
        if installation is None:
            return False
        installation.revoked_at = datetime.now(timezone.utc)
        # Absence of a grant row is how "no access" is represented locally.
        await self.session.execute(
            delete(GitHubInstallationRepository).where(
                GitHubInstallationRepository.installation_id == installation.id
            )
        )
        await self.session.commit()
        audit(
            INSTALLATION_REVOKED,
            installation_id=github_installation_id,
            account=installation.account_login,
        )
        return True

    async def _set_suspended(
        self, github_installation_id: int, suspended: bool
    ) -> bool:
        installation = await self.installations.get_by_github_id(
            github_installation_id
        )
        if installation is None:
            return False
        # Set-to-value, so redelivery is harmless.
        installation.suspended_at = (
            datetime.now(timezone.utc) if suspended else None
        )
        await self.session.commit()
        audit(
            INSTALLATION_SUSPENDED if suspended else INSTALLATION_UNSUSPENDED,
            installation_id=github_installation_id,
            account=installation.account_login,
        )
        return True

    # -- installation_repositories -----------------------------------------

    async def _handle_repositories(self, payload: dict) -> bool:
        action = str(payload.get("action") or "")
        if action not in REPOSITORY_ACTIONS:
            return False

        github_installation_id = installation_id_from(payload)
        if github_installation_id is None:
            return False
        installation = await self.installations.get_by_github_id(
            github_installation_id
        )
        if installation is None:
            # An installation we have never seen; nothing cached to update.
            return False

        if action == "added":
            added = payload.get("repositories_added") or []
            count = await self._add_repositories(installation, added)
            await self.session.commit()
            audit(
                REPOSITORIES_ADDED,
                installation_id=github_installation_id,
                count=count,
            )
            return count > 0

        removed = payload.get("repositories_removed") or []
        count = await self._remove_repositories(installation, removed)
        await self.session.commit()
        audit(
            REPOSITORIES_REMOVED,
            installation_id=github_installation_id,
            count=count,
        )
        return count > 0

    async def _add_repositories(
        self, installation: GitHubInstallation, items: list
    ) -> int:
        existing = {
            row.github_repository_id: row
            for row in await self._cached(installation)
        }
        now = datetime.now(timezone.utc)
        applied = 0
        for item in items:
            try:
                info = parse_repository(item)
            except (KeyError, TypeError, ValueError):
                continue
            row = existing.get(info.github_repository_id)
            if row is None:
                row = GitHubInstallationRepository(
                    installation_id=installation.id,
                    github_repository_id=info.github_repository_id,
                )
                self.session.add(row)
            # Upsert: a redelivered "added" refreshes rather than duplicates.
            row.owner = info.owner
            row.name = info.name
            row.full_name = info.full_name
            row.default_branch = info.default_branch
            row.private = info.private
            row.archived = info.archived
            row.disabled = info.disabled
            row.last_synced_at = now
            applied += 1
        return applied

    async def _remove_repositories(
        self, installation: GitHubInstallation, items: list
    ) -> int:
        ids = []
        for item in items:
            raw = (item or {}).get("id") if isinstance(item, dict) else None
            if raw is not None:
                try:
                    ids.append(int(raw))
                except (TypeError, ValueError):
                    continue
        if not ids:
            return 0
        result = await self.session.execute(
            delete(GitHubInstallationRepository).where(
                GitHubInstallationRepository.installation_id == installation.id,
                GitHubInstallationRepository.github_repository_id.in_(ids),
            )
        )
        # Redelivery deletes nothing the second time — still idempotent.
        return result.rowcount or 0

    async def _replace_repositories(
        self, installation: GitHubInstallation, items: list
    ) -> None:
        await self.session.execute(
            delete(GitHubInstallationRepository).where(
                GitHubInstallationRepository.installation_id == installation.id
            )
        )
        await self._add_repositories(installation, items)

    async def _cached(
        self, installation: GitHubInstallation
    ) -> list[GitHubInstallationRepository]:
        result = await self.session.execute(
            select(GitHubInstallationRepository).where(
                GitHubInstallationRepository.installation_id == installation.id
            )
        )
        return list(result.scalars().all())
