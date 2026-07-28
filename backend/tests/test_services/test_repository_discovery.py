"""Repository discovery: grant listing, sync, withdrawal, and the
registration authorisation gate.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    GitHubInstallation,
    GitHubInstallationRepository,
    Project,
    User,
    UserGitHubInstallation,
)
from app.services.github_app_api import RepositoryInfo
from app.services.installation_service import InstallationAccessError
from app.services.repository_discovery import RepositoryDiscoveryService


def _repo_info(repo_id: int = 900, full_name: str = "octocat/hello", **kw):
    owner, _, name = full_name.partition("/")
    base = {
        "github_repository_id": repo_id,
        "owner": owner,
        "name": name,
        "full_name": full_name,
        "default_branch": "main",
        "private": False,
        "archived": False,
        "disabled": False,
    }
    return RepositoryInfo(**{**base, **kw})


class FakeTokenService:
    """Hands back a token and a scripted repository list."""

    def __init__(self, repositories=None) -> None:
        self.repositories = repositories if repositories is not None else []
        self.token_calls: list[int] = []
        self._api = self

    async def get_installation_token(self, installation_id, repository_ids=None):
        from datetime import datetime, timedelta, timezone

        from app.services.github_app_api import InstallationToken

        self.token_calls.append(installation_id)
        return InstallationToken(
            token="ghs_scoped",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    async def list_installation_repositories(self, token: str):
        return self.repositories


async def _user(session: AsyncSession, gid: int = 1, login: str = "octocat") -> User:
    user = User(github_user_id=gid, github_login=login)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _installation(
    session: AsyncSession, user: User, gh_id: int = 500, **kw
) -> GitHubInstallation:
    installation = GitHubInstallation(
        github_installation_id=gh_id,
        account_id=1,
        account_login=kw.pop("account_login", "octocat"),
        **kw,
    )
    session.add(installation)
    await session.commit()
    await session.refresh(installation)
    session.add(
        UserGitHubInstallation(user_id=user.id, installation_id=installation.id)
    )
    await session.commit()
    return installation


async def _cached_count(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(GitHubInstallationRepository)
        )
    ).scalar_one()


# -- sync -------------------------------------------------------------------


async def test_sync_stores_granted_repositories(session: AsyncSession):
    user = await _user(session)
    installation = await _installation(session, user)
    tokens = FakeTokenService([_repo_info(900, "octocat/hello")])

    rows = await RepositoryDiscoveryService(session, tokens).sync_installation(
        installation
    )

    assert [r.full_name for r in rows] == ["octocat/hello"]
    assert tokens.token_calls == [500]


async def test_sync_updates_an_existing_repository_in_place(
    session: AsyncSession,
):
    user = await _user(session)
    installation = await _installation(session, user)
    service = RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(900, "octocat/hello")])
    )
    await service.sync_installation(installation)

    renamed = RepositoryDiscoveryService(
        session,
        FakeTokenService([_repo_info(900, "octocat/renamed", default_branch="dev")]),
    )
    rows = await renamed.sync_installation(installation)

    assert await _cached_count(session) == 1  # matched on id, not name
    assert rows[0].full_name == "octocat/renamed"
    assert rows[0].default_branch == "dev"


async def test_sync_removes_withdrawn_repositories(session: AsyncSession):
    """Withdrawn access is represented by absence."""
    user = await _user(session)
    installation = await _installation(session, user)
    await RepositoryDiscoveryService(
        session,
        FakeTokenService([_repo_info(900, "octocat/a"), _repo_info(901, "octocat/b")]),
    ).sync_installation(installation)
    assert await _cached_count(session) == 2

    rows = await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(900, "octocat/a")])
    ).sync_installation(installation)

    assert [r.github_repository_id for r in rows] == [900]
    assert await _cached_count(session) == 1


async def test_sync_refuses_a_suspended_installation(session: AsyncSession):
    from datetime import datetime, timezone

    user = await _user(session)
    installation = await _installation(
        session, user, suspended_at=datetime.now(timezone.utc)
    )
    with pytest.raises(InstallationAccessError, match="suspended"):
        await RepositoryDiscoveryService(
            session, FakeTokenService([])
        ).sync_installation(installation)


async def test_sync_all_skips_suspended_without_failing_the_rest(
    session: AsyncSession,
):
    from datetime import datetime, timezone

    user = await _user(session)
    await _installation(session, user, gh_id=500)
    await _installation(
        session,
        user,
        gh_id=501,
        account_login="acme",
        suspended_at=datetime.now(timezone.utc),
    )

    total = await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(900, "octocat/a")])
    ).sync_all_for_user(user)

    # The healthy installation still synced.
    assert total == 1


# -- listing ----------------------------------------------------------------


async def test_list_returns_only_repositories_from_your_installations(
    session: AsyncSession,
):
    alice = await _user(session, 1, "alice")
    mallory = await _user(session, 2, "mallory")
    alice_install = await _installation(session, alice, gh_id=500)
    mallory_install = await _installation(
        session, mallory, gh_id=501, account_login="mallory"
    )

    await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(900, "alice/repo")])
    ).sync_installation(alice_install)
    await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(901, "mallory/repo")])
    ).sync_installation(mallory_install)

    found = await RepositoryDiscoveryService(session).list_for_user(alice)
    assert [f.repository.full_name for f in found] == ["alice/repo"]


async def test_list_marks_already_registered_repositories(session: AsyncSession):
    user = await _user(session)
    installation = await _installation(session, user)
    await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(900, "octocat/hello")])
    ).sync_installation(installation)

    project = Project(
        user_id=user.id,
        name="octocat/hello",
        description="",
        repo_path="",
        github_repository_id=900,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    found = await RepositoryDiscoveryService(session).list_for_user(user)
    assert found[0].is_registered is True
    assert found[0].registered_project_id == project.id


async def test_registration_status_is_per_user(session: AsyncSession):
    """Another user registering the repo must not mark it registered for me."""
    alice = await _user(session, 1, "alice")
    mallory = await _user(session, 2, "mallory")
    installation = await _installation(session, alice, gh_id=500)
    # Both users can reach the same installation.
    session.add(
        UserGitHubInstallation(user_id=mallory.id, installation_id=installation.id)
    )
    await session.commit()

    await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(900, "octocat/hello")])
    ).sync_installation(installation)

    session.add(
        Project(
            user_id=mallory.id,
            name="octocat/hello",
            description="",
            repo_path="",
            github_repository_id=900,
        )
    )
    await session.commit()

    found = await RepositoryDiscoveryService(session).list_for_user(alice)
    assert found[0].is_registered is False


async def test_list_is_empty_without_installations(session: AsyncSession):
    user = await _user(session)
    assert await RepositoryDiscoveryService(session).list_for_user(user) == []


# -- find_granted: the authorisation gate ----------------------------------


async def test_find_granted_returns_a_granted_repository(session: AsyncSession):
    user = await _user(session)
    installation = await _installation(session, user)
    await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(900, "octocat/hello")])
    ).sync_installation(installation)

    repository, found_install = await RepositoryDiscoveryService(
        session
    ).find_granted(user, 900)
    assert repository.full_name == "octocat/hello"
    assert found_install.id == installation.id


async def test_find_granted_refuses_an_ungranted_repository(session: AsyncSession):
    """A fabricated repository id cannot be registered."""
    user = await _user(session)
    await _installation(session, user)
    with pytest.raises(InstallationAccessError, match="not available"):
        await RepositoryDiscoveryService(session).find_granted(user, 12345)


async def test_find_granted_refuses_another_users_repository(
    session: AsyncSession,
):
    alice = await _user(session, 1, "alice")
    mallory = await _user(session, 2, "mallory")
    mallory_install = await _installation(
        session, mallory, gh_id=501, account_login="mallory"
    )
    await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(901, "mallory/secret")])
    ).sync_installation(mallory_install)

    with pytest.raises(InstallationAccessError):
        await RepositoryDiscoveryService(session).find_granted(alice, 901)


async def test_find_granted_refusal_does_not_confirm_existence(
    session: AsyncSession,
):
    alice = await _user(session, 1, "alice")
    mallory = await _user(session, 2, "mallory")
    mallory_install = await _installation(
        session, mallory, gh_id=501, account_login="mallory"
    )
    await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(901, "mallory/secret")])
    ).sync_installation(mallory_install)

    with pytest.raises(InstallationAccessError) as real:
        await RepositoryDiscoveryService(session).find_granted(alice, 901)
    with pytest.raises(InstallationAccessError) as imaginary:
        await RepositoryDiscoveryService(session).find_granted(alice, 99999)

    assert str(real.value) == str(imaginary.value)
    assert "mallory/secret" not in str(real.value)


async def test_find_granted_refuses_a_suspended_installation(
    session: AsyncSession,
):
    from datetime import datetime, timezone

    user = await _user(session)
    installation = await _installation(session, user)
    await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(900, "octocat/hello")])
    ).sync_installation(installation)

    installation.suspended_at = datetime.now(timezone.utc)
    await session.commit()

    with pytest.raises(InstallationAccessError, match="suspended"):
        await RepositoryDiscoveryService(session).find_granted(user, 900)


@pytest.mark.parametrize("flag", ["archived", "disabled"])
async def test_find_granted_refuses_an_unusable_repository(
    session: AsyncSession, flag: str
):
    user = await _user(session)
    installation = await _installation(session, user)
    await RepositoryDiscoveryService(
        session,
        FakeTokenService([_repo_info(900, "octocat/hello", **{flag: True})]),
    ).sync_installation(installation)

    with pytest.raises(InstallationAccessError, match=flag):
        await RepositoryDiscoveryService(session).find_granted(user, 900)


async def test_withdrawn_repository_can_no_longer_be_found(
    session: AsyncSession,
):
    """After access is revoked and a sync runs, the gate closes."""
    user = await _user(session)
    installation = await _installation(session, user)
    await RepositoryDiscoveryService(
        session, FakeTokenService([_repo_info(900, "octocat/hello")])
    ).sync_installation(installation)
    await RepositoryDiscoveryService(session).find_granted(user, 900)

    await RepositoryDiscoveryService(session, FakeTokenService([])).sync_installation(
        installation
    )

    with pytest.raises(InstallationAccessError):
        await RepositoryDiscoveryService(session).find_granted(user, 900)
