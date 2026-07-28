"""Central resolution of the credential used for one repository operation.

The single rule this module exists to enforce: **in github_app mode there is
no path to the shared PAT.** The two modes are separate branches that never
converge, so a failure in the App path aborts the operation rather than
degrading to a broader credential.

Credentials are resolved immediately before each GitHub operation and thrown
away afterwards. Nothing here is cached on the resolver, and the returned
object is never persisted, logged, or sent to a client.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.config import settings
from app.core.enums import AuthMode
from app.models import (
    GitHubInstallation,
    GitHubInstallationRepository,
    Project,
    UserGitHubInstallation,
)
from app.services.github_app_auth import GitHubAppConfigError
from app.services.installation_service import (
    InstallationAccessError,
    assert_active,
)

logger = logging.getLogger(__name__)

# One message for every access failure in github_app mode. Callers must not be
# able to tell "revoked" from "never granted" from "not yours".
ACCESS_LOST_MESSAGE = (
    "GitHub App access to this repository is no longer available. "
    "Reinstall or update repository access."
)

# Audit events.
CREDENTIAL_RESOLVED = "github.credential.resolved"
CREDENTIAL_DENIED = "github.credential.denied"
CREDENTIAL_INVALIDATED = "github.credential.invalidated"


class RepoOperation(StrEnum):
    """What the credential is for. Drives the permission check."""

    clone = "clone"
    push = "push"
    pull_request = "pull_request"


# Minimum installation permissions per operation, as GitHub reports them.
_REQUIRED_PERMISSIONS: dict[RepoOperation, dict[str, set[str]]] = {
    RepoOperation.clone: {"contents": {"read", "write"}},
    RepoOperation.push: {"contents": {"write"}},
    RepoOperation.pull_request: {
        "contents": {"write"},
        "pull_requests": {"write"},
    },
}


class RepositoryAccessError(Exception):
    """The operation may not proceed. Message is always user-safe."""


@dataclass
class GitCredentials:
    """One credential, for one operation, for one repository."""

    token: str
    committer_name: str
    committer_email: str
    mode: AuthMode
    repository_full_name: str
    # Populated in github_app mode only.
    github_installation_id: int | None = None
    github_repository_id: int | None = None
    expires_at: datetime | None = None

    @property
    def is_installation(self) -> bool:
        return self.mode == AuthMode.github_app

    def seconds_remaining(self) -> float | None:
        if self.expires_at is None:
            return None
        return (self.expires_at - datetime.now(timezone.utc)).total_seconds()

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # A stray repr in a log or traceback must never carry the token.
        return (
            f"GitCredentials(mode={self.mode}, "
            f"repository={self.repository_full_name!r}, "
            f"installation={self.github_installation_id})"
        )


class GitHubCredentialResolver:
    """Resolves the credential for a repository operation.

    `token_service` is required in github_app mode; tests inject one backed by
    an in-memory store so no Redis or GitHub call is made.
    """

    def __init__(self, session: AsyncSession, token_service=None) -> None:
        self.session = session
        self._token_service = token_service

    # -- Public -----------------------------------------------------------

    async def resolve(
        self,
        project_id: int,
        operation: RepoOperation,
        user_id: int | None = None,
    ) -> GitCredentials:
        """Fresh credentials for one operation.

        Every call re-reads the project, its installation and its repository
        grant from the database — nothing is carried over from a previous
        resolution or from a queued job payload.
        """
        project = await self.session.get(Project, project_id)
        if project is None:
            raise RepositoryAccessError(f"Project {project_id} not found")

        if settings.is_github_app_mode():
            return await self._resolve_installation(project, operation, user_id)
        return self._resolve_local(project)

    async def invalidate(self, credentials: GitCredentials) -> None:
        """Drop a cached token GitHub has rejected, so it is never reused."""
        if not credentials.is_installation or self._token_service is None:
            return
        await self._token_service.invalidate(
            credentials.github_installation_id,
            [credentials.github_repository_id]
            if credentials.github_repository_id
            else None,
        )
        audit(
            CREDENTIAL_INVALIDATED,
            installation_id=credentials.github_installation_id,
            repository=credentials.repository_full_name,
        )

    # -- local ------------------------------------------------------------

    def _resolve_local(self, project: Project) -> GitCredentials:
        if not settings.github_token:
            raise RepositoryAccessError(
                "GITHUB_TOKEN is not set — required to access GitHub "
                "repositories in local mode. Add it to .env and restart the "
                "backend and worker."
            )
        credentials = GitCredentials(
            token=settings.github_token,
            committer_name=settings.local_commit_name,
            committer_email=settings.local_commit_email,
            mode=AuthMode.local,
            repository_full_name=f"{project.github_owner}/{project.github_repo}",
        )
        audit(
            CREDENTIAL_RESOLVED,
            mode="local",
            repository=credentials.repository_full_name,
            project_id=project.id,
        )
        return credentials

    # -- github_app -------------------------------------------------------

    async def _resolve_installation(
        self,
        project: Project,
        operation: RepoOperation,
        user_id: int | None,
    ) -> GitCredentials:
        def deny(reason: str) -> RepositoryAccessError:
            audit(
                CREDENTIAL_DENIED,
                reason=reason,
                project_id=project.id,
                user_id=user_id,
                operation=str(operation),
            )
            return RepositoryAccessError(ACCESS_LOST_MESSAGE)

        # 1. Ownership. Re-derived from the row, never from a job payload.
        if user_id is not None and project.user_id != user_id:
            raise deny("not_owner")

        # 2. The project must have been registered through an installation.
        if project.github_installation_id is None:
            raise deny("no_installation_link")

        # 3. Installation must exist and be neither suspended nor revoked.
        installation = await self.session.get(
            GitHubInstallation, project.github_installation_id
        )
        if installation is None:
            raise deny("installation_missing")
        try:
            assert_active(installation)
        except InstallationAccessError:
            raise deny(
                "installation_suspended"
                if installation.is_suspended
                else "installation_revoked"
            ) from None

        # 3b. The project's OWNER must still be linked to this installation.
        #     Installation liveness alone is not enough: an installation can
        #     stay active for an organisation while one member's access is
        #     withdrawn. Without this, that member's existing projects would
        #     keep minting tokens. This is also the check that gives the
        #     worker path real authorisation — there the user_id comparison
        #     above is a tautology, because the owner is derived from the row.
        link = await self.session.execute(
            select(UserGitHubInstallation.id).where(
                UserGitHubInstallation.user_id == project.user_id,
                UserGitHubInstallation.installation_id == installation.id,
            )
        )
        if link.scalar_one_or_none() is None:
            raise deny("owner_not_linked_to_installation")

        # 4. Repository grant. The cache is a fast pre-check only — it can
        #    refuse, but the token exchange below is what actually authorises.
        grant = await self._repository_grant(project, installation)
        if grant is None:
            raise deny("repository_not_granted")
        if grant.archived:
            raise deny("repository_archived")
        if grant.disabled:
            raise deny("repository_disabled")

        # 5. Commit identity must be configured before we can commit at all.
        missing = settings.missing_commit_identity_settings()
        if missing:
            raise RepositoryAccessError(
                "GitHub App commit identity is not configured — set "
                + " and ".join(missing)
                + ". Commits cannot be attributed without it."
            )

        # 6. Mint a token scoped to this one repository.
        if self._token_service is None:
            raise RepositoryAccessError(
                "The GitHub App is not configured on this server, so "
                "repository access is unavailable."
            )
        try:
            token = await self._token_service.get_installation_token(
                installation.github_installation_id,
                repository_ids=[project.github_repository_id]
                if project.github_repository_id
                else None,
            )
        except GitHubAppConfigError as exc:
            # Operator-facing configuration problem, not an access problem.
            raise RepositoryAccessError(str(exc)) from None
        except Exception as exc:
            logger.warning(
                "Installation token could not be minted for installation %s: %s",
                installation.github_installation_id,
                type(exc).__name__,
            )
            raise deny("token_mint_failed") from None

        # 7. GitHub's own view of what this token may do.
        self._assert_permissions(token.permissions, operation, deny)

        credentials = GitCredentials(
            token=token.token,
            committer_name=settings.github_app_commit_name.strip(),
            committer_email=settings.github_app_commit_email.strip(),
            mode=AuthMode.github_app,
            repository_full_name=f"{project.github_owner}/{project.github_repo}",
            github_installation_id=installation.github_installation_id,
            github_repository_id=project.github_repository_id,
            expires_at=token.expires_at,
        )
        audit(
            CREDENTIAL_RESOLVED,
            mode="github_app",
            installation_id=installation.github_installation_id,
            repository=credentials.repository_full_name,
            project_id=project.id,
            operation=str(operation),
            expires_in_seconds=int(token.seconds_remaining()),
        )
        return credentials

    async def _repository_grant(
        self, project: Project, installation: GitHubInstallation
    ) -> GitHubInstallationRepository | None:
        if project.github_repository_id is None:
            return None
        result = await self.session.execute(
            select(GitHubInstallationRepository).where(
                GitHubInstallationRepository.installation_id == installation.id,
                GitHubInstallationRepository.github_repository_id
                == project.github_repository_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _assert_permissions(granted: dict, operation: RepoOperation, deny) -> None:
        """GitHub reports what the installation token may do; require it."""
        for scope, acceptable in _REQUIRED_PERMISSIONS[operation].items():
            if str(granted.get(scope, "")) not in acceptable:
                raise deny(f"missing_permission_{scope}")
