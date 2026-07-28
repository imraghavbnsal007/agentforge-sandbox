"""Credential resolution: which token is used, and when access is refused.

The property that matters most here: in github_app mode there is no path
that reaches the shared PAT.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AuthMode
from app.models import (
    GitHubInstallation,
    GitHubInstallationRepository,
    Project,
    User,
    UserGitHubInstallation,
)
from app.services.github_app_api import InstallationToken
from app.services.github_credentials import (
    ACCESS_LOST_MESSAGE,
    GitHubCredentialResolver,
    RepoOperation,
    RepositoryAccessError,
)

PAT = "ghp_local_personal_access_token"

FULL_PERMISSIONS = {"contents": "write", "pull_requests": "write"}


@pytest.fixture(autouse=True)
def _app_mode_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "github_token", PAT)
    monkeypatch.setattr(settings, "github_app_commit_name", "AgentForge[bot]")
    monkeypatch.setattr(
        settings, "github_app_commit_email", "bot@agentforge.example"
    )


@pytest.fixture
def app_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)


class FakeTokenService:
    """Mints a scripted installation token; records what was asked for."""

    def __init__(self, permissions: dict | None = None, error: Exception | None = None):
        self.permissions = (
            permissions if permissions is not None else dict(FULL_PERMISSIONS)
        )
        self.error = error
        self.calls: list[tuple[int, list[int] | None]] = []
        self.invalidated: list[tuple[int, list[int] | None]] = []
        self.counter = 0

    async def get_installation_token(self, installation_id, repository_ids=None):
        self.calls.append((installation_id, repository_ids))
        if self.error is not None:
            raise self.error
        self.counter += 1
        return InstallationToken(
            token=f"ghs_installation_{self.counter}",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            permissions=self.permissions,
        )

    async def invalidate(self, installation_id, repository_ids=None):
        self.invalidated.append((installation_id, repository_ids))


async def _setup(
    session: AsyncSession,
    *,
    granted: bool = True,
    suspended: bool = False,
    revoked: bool = False,
    archived: bool = False,
    disabled: bool = False,
    linked: bool = True,
) -> tuple[User, Project]:
    user = User(github_user_id=1, github_login="octocat")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    installation = GitHubInstallation(
        github_installation_id=500,
        account_id=1,
        account_login="octocat",
        suspended_at=datetime.now(timezone.utc) if suspended else None,
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    session.add(installation)
    await session.commit()
    await session.refresh(installation)
    session.add(
        UserGitHubInstallation(user_id=user.id, installation_id=installation.id)
    )

    if granted:
        session.add(
            GitHubInstallationRepository(
                installation_id=installation.id,
                github_repository_id=900,
                owner="octocat",
                name="hello",
                full_name="octocat/hello",
                default_branch="main",
                private=False,
                archived=archived,
                disabled=disabled,
            )
        )

    project = Project(
        user_id=user.id,
        name="octocat/hello",
        description="",
        repo_path="",
        repo_url="https://github.com/octocat/hello.git",
        default_branch="main",
        github_owner="octocat",
        github_repo="hello",
        github_installation_id=installation.id if linked else None,
        github_repository_id=900,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return user, project


# -- local mode -------------------------------------------------------------


async def test_local_mode_uses_the_personal_access_token(session: AsyncSession):
    user, project = await _setup(session)
    credentials = await GitHubCredentialResolver(session).resolve(
        project.id, RepoOperation.clone, user_id=user.id
    )
    assert credentials.token == PAT
    assert credentials.mode == AuthMode.local
    assert credentials.committer_name == settings.local_commit_name


async def test_local_mode_reports_a_missing_pat_clearly(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_token", "")
    _, project = await _setup(session)
    with pytest.raises(RepositoryAccessError, match="GITHUB_TOKEN"):
        await GitHubCredentialResolver(session).resolve(
            project.id, RepoOperation.clone
        )


async def test_local_mode_ignores_installation_state(session: AsyncSession):
    """A suspended installation must not affect the local PAT workflow."""
    user, project = await _setup(session, suspended=True)
    credentials = await GitHubCredentialResolver(session).resolve(
        project.id, RepoOperation.push, user_id=user.id
    )
    assert credentials.token == PAT


# -- github_app mode --------------------------------------------------------


async def test_app_mode_uses_an_installation_token(
    session: AsyncSession, app_mode
):
    user, project = await _setup(session)
    tokens = FakeTokenService()
    credentials = await GitHubCredentialResolver(session, tokens).resolve(
        project.id, RepoOperation.clone, user_id=user.id
    )
    assert credentials.token == "ghs_installation_1"
    assert credentials.mode == AuthMode.github_app
    assert credentials.github_installation_id == 500


async def test_app_mode_scopes_the_token_to_the_one_repository(
    session: AsyncSession, app_mode
):
    user, project = await _setup(session)
    tokens = FakeTokenService()
    await GitHubCredentialResolver(session, tokens).resolve(
        project.id, RepoOperation.clone, user_id=user.id
    )
    assert tokens.calls == [(500, [900])]


async def test_app_mode_uses_the_configured_commit_identity(
    session: AsyncSession, app_mode
):
    user, project = await _setup(session)
    credentials = await GitHubCredentialResolver(
        session, FakeTokenService()
    ).resolve(project.id, RepoOperation.push, user_id=user.id)
    assert credentials.committer_name == "AgentForge[bot]"
    assert credentials.committer_email == "bot@agentforge.example"


@pytest.mark.parametrize("missing", ["name", "email"])
async def test_app_mode_requires_a_configured_commit_identity(
    session: AsyncSession, app_mode, monkeypatch: pytest.MonkeyPatch, missing: str
):
    """No invented noreply address — refuse until it is configured."""
    monkeypatch.setattr(settings, f"github_app_commit_{missing}", "")
    user, project = await _setup(session)
    with pytest.raises(RepositoryAccessError, match="commit identity"):
        await GitHubCredentialResolver(session, FakeTokenService()).resolve(
            project.id, RepoOperation.push, user_id=user.id
        )


# -- no PAT fallback --------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"suspended": True},
        {"revoked": True},
        {"granted": False},
        {"archived": True},
        {"disabled": True},
        {"linked": False},
    ],
    ids=["suspended", "revoked", "not-granted", "archived", "disabled", "unlinked"],
)
async def test_app_mode_never_falls_back_to_the_pat(
    session: AsyncSession, app_mode, kwargs: dict
):
    """Every failure mode must abort — never degrade to the shared token."""
    user, project = await _setup(session, **kwargs)
    with pytest.raises(RepositoryAccessError) as excinfo:
        await GitHubCredentialResolver(session, FakeTokenService()).resolve(
            project.id, RepoOperation.clone, user_id=user.id
        )
    assert PAT not in str(excinfo.value)


async def test_app_mode_refuses_when_the_token_cannot_be_minted(
    session: AsyncSession, app_mode
):
    user, project = await _setup(session)
    tokens = FakeTokenService(error=RuntimeError("GitHub unavailable"))
    with pytest.raises(RepositoryAccessError, match="no longer available"):
        await GitHubCredentialResolver(session, tokens).resolve(
            project.id, RepoOperation.clone, user_id=user.id
        )


async def test_app_mode_refuses_without_a_token_service(
    session: AsyncSession, app_mode
):
    user, project = await _setup(session)
    with pytest.raises(RepositoryAccessError, match="not configured"):
        await GitHubCredentialResolver(session, None).resolve(
            project.id, RepoOperation.clone, user_id=user.id
        )


# -- access failures are indistinguishable ---------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [{"suspended": True}, {"revoked": True}, {"granted": False}],
    ids=["suspended", "revoked", "not-granted"],
)
async def test_access_failures_share_one_message(
    session: AsyncSession, app_mode, kwargs: dict
):
    user, project = await _setup(session, **kwargs)
    with pytest.raises(RepositoryAccessError) as excinfo:
        await GitHubCredentialResolver(session, FakeTokenService()).resolve(
            project.id, RepoOperation.clone, user_id=user.id
        )
    assert str(excinfo.value) == ACCESS_LOST_MESSAGE


# -- ownership --------------------------------------------------------------


async def test_another_users_project_is_refused(session: AsyncSession, app_mode):
    _, project = await _setup(session)
    other = User(github_user_id=999, github_login="mallory")
    session.add(other)
    await session.commit()
    await session.refresh(other)

    with pytest.raises(RepositoryAccessError) as excinfo:
        await GitHubCredentialResolver(session, FakeTokenService()).resolve(
            project.id, RepoOperation.clone, user_id=other.id
        )
    assert str(excinfo.value) == ACCESS_LOST_MESSAGE


async def test_unknown_project_is_refused(session: AsyncSession, app_mode):
    with pytest.raises(RepositoryAccessError):
        await GitHubCredentialResolver(session, FakeTokenService()).resolve(
            424242, RepoOperation.clone
        )


# -- permissions ------------------------------------------------------------


@pytest.mark.parametrize(
    "operation,permissions",
    [
        (RepoOperation.clone, {}),
        (RepoOperation.push, {"contents": "read"}),
        (RepoOperation.pull_request, {"contents": "write"}),
        (RepoOperation.pull_request, {"pull_requests": "write"}),
    ],
    ids=["clone-none", "push-readonly", "pr-no-pulls", "pr-no-contents"],
)
async def test_insufficient_permissions_block_the_operation(
    session: AsyncSession, app_mode, operation, permissions: dict
):
    user, project = await _setup(session)
    tokens = FakeTokenService(permissions=permissions)
    with pytest.raises(RepositoryAccessError, match="no longer available"):
        await GitHubCredentialResolver(session, tokens).resolve(
            project.id, operation, user_id=user.id
        )


async def test_read_only_contents_is_enough_to_clone(
    session: AsyncSession, app_mode
):
    user, project = await _setup(session)
    tokens = FakeTokenService(permissions={"contents": "read"})
    credentials = await GitHubCredentialResolver(session, tokens).resolve(
        project.id, RepoOperation.clone, user_id=user.id
    )
    assert credentials.token.startswith("ghs_")


# -- invalidation -----------------------------------------------------------


async def test_invalidate_drops_the_scoped_cache_entry(
    session: AsyncSession, app_mode
):
    user, project = await _setup(session)
    tokens = FakeTokenService()
    resolver = GitHubCredentialResolver(session, tokens)
    credentials = await resolver.resolve(
        project.id, RepoOperation.push, user_id=user.id
    )
    await resolver.invalidate(credentials)
    assert tokens.invalidated == [(500, [900])]


async def test_resolving_twice_mints_independently(
    session: AsyncSession, app_mode
):
    """Credentials are operation-scoped — nothing is held between calls."""
    user, project = await _setup(session)
    tokens = FakeTokenService()
    resolver = GitHubCredentialResolver(session, tokens)
    first = await resolver.resolve(project.id, RepoOperation.clone, user_id=user.id)
    second = await resolver.resolve(project.id, RepoOperation.push, user_id=user.id)
    assert first.token != second.token
    assert len(tokens.calls) == 2


# -- secret hygiene ---------------------------------------------------------


async def test_repr_never_exposes_the_token(session: AsyncSession, app_mode):
    user, project = await _setup(session)
    credentials = await GitHubCredentialResolver(
        session, FakeTokenService()
    ).resolve(project.id, RepoOperation.clone, user_id=user.id)
    assert credentials.token not in repr(credentials)
    assert "octocat/hello" in repr(credentials)
