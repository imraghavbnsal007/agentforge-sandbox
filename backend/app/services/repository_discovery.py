"""Discovering which repositories a user may register.

Replaces "paste any GitHub URL" in github_app mode. The only repositories a
user can see — or register — are those their own installations currently
grant. That set comes from GitHub, authenticated with an installation token,
and is cached locally so the picker does not hit the API on every page load.

Withdrawn access is represented by *absence*: a sync deletes rows GitHub no
longer reports, so "is this row present" is the local answer to "may we still
touch this repository".
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    GitHubInstallation,
    GitHubInstallationRepository,
    Project,
    User,
    UserGitHubInstallation,
)
from app.services.github_app_api import RepositoryInfo
from app.services.installation_service import (
    InstallationAccessError,
    assert_active,
)

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredRepository:
    """A repository plus the local context the picker needs."""

    repository: GitHubInstallationRepository
    installation: GitHubInstallation
    registered_project_id: int | None = None

    @property
    def is_registered(self) -> bool:
        return self.registered_project_id is not None


class RepositoryDiscoveryService:
    def __init__(self, session: AsyncSession, token_service=None) -> None:
        self.session = session
        self._token_service = token_service

    # -- Reads ------------------------------------------------------------

    async def list_for_user(self, user: User) -> list[DiscoveredRepository]:
        """Every granted repository across the user's installations, with
        registration status resolved in one pass."""
        result = await self.session.execute(
            select(GitHubInstallationRepository, GitHubInstallation)
            .join(
                GitHubInstallation,
                GitHubInstallation.id
                == GitHubInstallationRepository.installation_id,
            )
            .join(
                UserGitHubInstallation,
                UserGitHubInstallation.installation_id == GitHubInstallation.id,
            )
            .where(UserGitHubInstallation.user_id == user.id)
            .order_by(GitHubInstallationRepository.full_name)
        )
        rows = list(result.all())
        if not rows:
            return []

        registered = await self._registered_repository_ids(user)
        return [
            DiscoveredRepository(
                repository=repository,
                installation=installation,
                registered_project_id=registered.get(
                    repository.github_repository_id
                ),
            )
            for repository, installation in rows
        ]

    async def _registered_repository_ids(self, user: User) -> dict[int, int]:
        """github_repository_id -> project id, for this user only."""
        result = await self.session.execute(
            select(Project.github_repository_id, Project.id).where(
                Project.user_id == user.id,
                Project.github_repository_id.is_not(None),
            )
        )
        return {repo_id: project_id for repo_id, project_id in result.all()}

    async def find_granted(
        self, user: User, github_repository_id: int
    ) -> tuple[GitHubInstallationRepository, GitHubInstallation]:
        """Resolve a repository the user may actually use, or refuse.

        This is the authorisation gate for registration: a caller cannot
        register a repository by inventing an id, because the row must exist,
        be reachable through one of *their* installations, and be usable.
        """
        result = await self.session.execute(
            select(GitHubInstallationRepository, GitHubInstallation)
            .join(
                GitHubInstallation,
                GitHubInstallation.id
                == GitHubInstallationRepository.installation_id,
            )
            .join(
                UserGitHubInstallation,
                UserGitHubInstallation.installation_id == GitHubInstallation.id,
            )
            .where(
                UserGitHubInstallation.user_id == user.id,
                GitHubInstallationRepository.github_repository_id
                == github_repository_id,
            )
        )
        row = result.first()
        if row is None:
            # Same message whether it does not exist or is not theirs.
            raise InstallationAccessError(
                "That repository is not available to your account. Check the "
                "GitHub App installation grants access to it."
            )
        repository, installation = row
        assert_active(installation)
        if not repository.is_usable:
            state = "archived" if repository.archived else "disabled"
            raise InstallationAccessError(
                f"{repository.full_name} is {state} on GitHub and cannot "
                "receive pull requests."
            )
        return repository, installation

    # -- Sync -------------------------------------------------------------

    async def sync_installation(
        self, installation: GitHubInstallation
    ) -> list[GitHubInstallationRepository]:
        """Refresh the cache from GitHub for one installation.

        Rows GitHub no longer reports are deleted, so withdrawn access takes
        effect locally the moment a sync runs.
        """
        assert_active(installation)
        if self._token_service is None:
            raise InstallationAccessError(
                "Repository sync is unavailable: the GitHub App is not "
                "configured on this server."
            )

        token = await self._token_service.get_installation_token(
            installation.github_installation_id
        )
        from app.services.github_app_api import GitHubAppAPI

        api = getattr(self._token_service, "_api", None) or GitHubAppAPI()
        remote = await api.list_installation_repositories(token.token)

        await self._apply_sync(installation, remote)
        await self.session.commit()
        logger.info(
            "Synced %d repositories for installation %s",
            len(remote),
            installation.github_installation_id,
        )
        return await self._cached_for(installation)

    async def _apply_sync(
        self, installation: GitHubInstallation, remote: list[RepositoryInfo]
    ) -> None:
        existing = {r.github_repository_id: r for r in await self._cached_for(installation)}
        seen: set[int] = set()
        now = datetime.now(timezone.utc)

        for info in remote:
            seen.add(info.github_repository_id)
            row = existing.get(info.github_repository_id)
            if row is None:
                row = GitHubInstallationRepository(
                    installation_id=installation.id,
                    github_repository_id=info.github_repository_id,
                )
                self.session.add(row)
            row.owner = info.owner
            row.name = info.name
            row.full_name = info.full_name
            row.default_branch = info.default_branch
            row.private = info.private
            row.archived = info.archived
            row.disabled = info.disabled
            row.last_synced_at = now

        withdrawn = set(existing) - seen
        if withdrawn:
            # Absence is how revoked access is represented locally.
            await self.session.execute(
                delete(GitHubInstallationRepository).where(
                    GitHubInstallationRepository.installation_id
                    == installation.id,
                    GitHubInstallationRepository.github_repository_id.in_(
                        withdrawn
                    ),
                )
            )
            logger.info(
                "Removed %d withdrawn repositories from installation %s",
                len(withdrawn),
                installation.github_installation_id,
            )
        installation.last_synced_at = now

    async def _cached_for(
        self, installation: GitHubInstallation
    ) -> list[GitHubInstallationRepository]:
        result = await self.session.execute(
            select(GitHubInstallationRepository)
            .where(GitHubInstallationRepository.installation_id == installation.id)
            .order_by(GitHubInstallationRepository.full_name)
        )
        return list(result.scalars().all())

    async def sync_all_for_user(self, user: User) -> int:
        """Refresh every active installation the user has. Returns the count
        of repositories now visible."""
        result = await self.session.execute(
            select(GitHubInstallation)
            .join(
                UserGitHubInstallation,
                UserGitHubInstallation.installation_id == GitHubInstallation.id,
            )
            .where(UserGitHubInstallation.user_id == user.id)
        )
        total = 0
        for installation in result.scalars().all():
            if not installation.is_active:
                # Skip rather than fail the whole refresh: one suspended
                # installation must not hide the others.
                continue
            try:
                total += len(await self.sync_installation(installation))
            except InstallationAccessError:
                logger.warning(
                    "Skipped sync for installation %s",
                    installation.github_installation_id,
                )
        return total
