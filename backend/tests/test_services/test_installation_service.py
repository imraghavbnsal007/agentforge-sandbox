"""Installation ownership verification, linking, and status gating.

The central property under test: an installation id supplied by a caller is
never trusted — it is only accepted when GitHub reports it in that user's own
installation list.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GitHubInstallation, User, UserGitHubInstallation
from app.services.github_app_api import GitHubAppAPI, InstallationInfo
from app.services.installation_service import (
    InstallationAccessError,
    InstallationService,
    assert_active,
)


@pytest.fixture(autouse=True)
def _stub_app_jwt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.installation_service.generate_app_jwt",
        lambda: "app.jwt.value",
    )


def _info(installation_id: int = 500, **overrides) -> InstallationInfo:
    base = {
        "github_installation_id": installation_id,
        "account_id": 4242,
        "account_login": "octocat",
        "account_type": "User",
        "target_type": "User",
        "repository_selection": "selected",
        "suspended_at": None,
        "permissions": {"contents": "write"},
    }
    return InstallationInfo(**{**base, **overrides})


class FakeAPI(GitHubAppAPI):
    """Scripted GitHub App API. Records the user token it was handed so tests
    can assert it is used exactly once and never stored."""

    def __init__(self, user_installations=None, app_installation=None) -> None:
        super().__init__()
        self.user_installations = user_installations or []
        self.app_installation = app_installation
        self.user_tokens_seen: list[str] = []

    async def list_user_installations(self, user_access_token: str):
        self.user_tokens_seen.append(user_access_token)
        return self.user_installations

    async def get_installation(self, app_jwt: str, github_installation_id: int):
        if self.app_installation is None:
            raise AssertionError("app-level read not scripted")
        return self.app_installation


@pytest.fixture
async def user(session: AsyncSession) -> User:
    user = User(github_user_id=4242, github_login="octocat")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.fixture
async def other_user(session: AsyncSession) -> User:
    user = User(github_user_id=9999, github_login="mallory")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _link_count(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(UserGitHubInstallation)
        )
    ).scalar_one()


# -- verification -----------------------------------------------------------


async def test_installation_in_the_users_list_is_linked(
    session: AsyncSession, user: User
):
    api = FakeAPI(user_installations=[_info()], app_installation=_info())
    installation = await InstallationService(session, api).link_installation_for_user(
        user, 500, "gho_user_token"
    )

    assert installation.github_installation_id == 500
    assert installation.account_login == "octocat"
    assert await _link_count(session) == 1


async def test_forged_installation_id_is_rejected(
    session: AsyncSession, user: User
):
    """The user's real list contains 500; they claim 999."""
    api = FakeAPI(user_installations=[_info(500)])
    with pytest.raises(InstallationAccessError, match="not available to your account"):
        await InstallationService(session, api).link_installation_for_user(
            user, 999, "gho_user_token"
        )
    assert await _link_count(session) == 0


async def test_rejection_message_does_not_confirm_existence(
    session: AsyncSession, user: User
):
    api = FakeAPI(user_installations=[])
    with pytest.raises(InstallationAccessError) as excinfo:
        await InstallationService(session, api).link_installation_for_user(
            user, 12345, "t"
        )
    assert "12345" not in str(excinfo.value)


async def test_user_token_is_used_once_and_not_retained(
    session: AsyncSession, user: User
):
    api = FakeAPI(user_installations=[_info()], app_installation=_info())
    service = InstallationService(session, api)
    await service.link_installation_for_user(user, 500, "gho_secret_token")

    assert api.user_tokens_seen == ["gho_secret_token"]
    # Nothing on the persisted rows may carry it.
    installation = await service.get_by_github_id(500)
    assert "gho_secret_token" not in str(installation.__dict__)


async def test_duplicate_callback_does_not_duplicate_the_link(
    session: AsyncSession, user: User
):
    api = FakeAPI(user_installations=[_info()], app_installation=_info())
    service = InstallationService(session, api)
    await service.link_installation_for_user(user, 500, "t")
    await service.link_installation_for_user(user, 500, "t")

    assert await _link_count(session) == 1
    installations = (
        await session.execute(select(func.count()).select_from(GitHubInstallation))
    ).scalar_one()
    assert installations == 1


async def test_two_users_may_link_the_same_installation(
    session: AsyncSession, user: User, other_user: User
):
    api = FakeAPI(user_installations=[_info()], app_installation=_info())
    service = InstallationService(session, api)
    await service.link_installation_for_user(user, 500, "t")
    await service.link_installation_for_user(other_user, 500, "t")
    assert await _link_count(session) == 2


async def test_app_level_read_refreshes_stale_user_side_data(
    session: AsyncSession, user: User
):
    """The user list can lag; the app-level record wins."""
    api = FakeAPI(
        user_installations=[_info(repository_selection="selected")],
        app_installation=_info(repository_selection="all"),
    )
    installation = await InstallationService(session, api).link_installation_for_user(
        user, 500, "t"
    )
    assert installation.repository_selection == "all"


async def test_link_survives_an_unavailable_app_level_read(
    session: AsyncSession, user: User
):
    """A legitimate installation must not be refused because the app-level
    read failed."""
    api = FakeAPI(user_installations=[_info()], app_installation=None)
    installation = await InstallationService(session, api).link_installation_for_user(
        user, 500, "t"
    )
    assert installation.github_installation_id == 500


# -- suspension and revocation ---------------------------------------------


async def test_suspended_installation_is_recorded_as_suspended(
    session: AsyncSession, user: User
):
    suspended = _info(suspended_at=datetime.now(timezone.utc))
    api = FakeAPI(user_installations=[suspended], app_installation=suspended)
    installation = await InstallationService(session, api).link_installation_for_user(
        user, 500, "t"
    )
    assert installation.is_suspended is True
    assert installation.is_active is False


def test_assert_active_rejects_a_suspended_installation():
    installation = GitHubInstallation(
        github_installation_id=1,
        account_login="acme",
        suspended_at=datetime.now(timezone.utc),
    )
    with pytest.raises(InstallationAccessError, match="suspended"):
        assert_active(installation)


def test_assert_active_rejects_a_revoked_installation():
    installation = GitHubInstallation(
        github_installation_id=1,
        account_login="acme",
        revoked_at=datetime.now(timezone.utc),
    )
    with pytest.raises(InstallationAccessError, match="removed"):
        assert_active(installation)


def test_assert_active_passes_a_healthy_installation():
    assert_active(
        GitHubInstallation(github_installation_id=1, account_login="acme")
    )


async def test_unsuspending_clears_the_flag(session: AsyncSession, user: User):
    suspended = _info(suspended_at=datetime.now(timezone.utc))
    api = FakeAPI(user_installations=[suspended], app_installation=suspended)
    service = InstallationService(session, api)
    await service.link_installation_for_user(user, 500, "t")

    api.app_installation = _info(suspended_at=None)
    refreshed = await service.sync_from_github(500)
    assert refreshed.is_suspended is False
    assert refreshed.is_active is True


async def test_mark_revoked_blocks_future_use_but_keeps_the_row(
    session: AsyncSession, user: User
):
    api = FakeAPI(user_installations=[_info()], app_installation=_info())
    service = InstallationService(session, api)
    await service.link_installation_for_user(user, 500, "t")

    await service.mark_revoked(500)

    installation = await service.get_by_github_id(500)
    assert installation is not None  # history preserved
    assert installation.is_active is False


# -- require_usable ---------------------------------------------------------


async def test_require_usable_returns_a_linked_active_installation(
    session: AsyncSession, user: User
):
    api = FakeAPI(user_installations=[_info()], app_installation=_info())
    service = InstallationService(session, api)
    await service.link_installation_for_user(user, 500, "t")
    assert (await service.require_usable(user, 500)).github_installation_id == 500


async def test_require_usable_refuses_another_users_installation(
    session: AsyncSession, user: User, other_user: User
):
    api = FakeAPI(user_installations=[_info()], app_installation=_info())
    service = InstallationService(session, api)
    await service.link_installation_for_user(user, 500, "t")

    with pytest.raises(InstallationAccessError):
        await service.require_usable(other_user, 500)


async def test_require_usable_refuses_an_unknown_installation(
    session: AsyncSession, user: User
):
    with pytest.raises(InstallationAccessError):
        await InstallationService(session, FakeAPI()).require_usable(user, 777)


async def test_require_usable_refuses_a_suspended_installation(
    session: AsyncSession, user: User
):
    suspended = _info(suspended_at=datetime.now(timezone.utc))
    api = FakeAPI(user_installations=[suspended], app_installation=suspended)
    service = InstallationService(session, api)
    await service.link_installation_for_user(user, 500, "t")

    with pytest.raises(InstallationAccessError, match="suspended"):
        await service.require_usable(user, 500)


# -- listing ----------------------------------------------------------------


async def test_list_for_user_returns_only_their_installations(
    session: AsyncSession, user: User, other_user: User
):
    api = FakeAPI(user_installations=[_info(500)], app_installation=_info(500))
    service = InstallationService(session, api)
    await service.link_installation_for_user(user, 500, "t")

    api.user_installations = [_info(600, account_login="acme")]
    api.app_installation = _info(600, account_login="acme")
    await service.link_installation_for_user(other_user, 600, "t")

    mine = await service.list_for_user(user)
    assert [i.github_installation_id for i in mine] == [500]
