"""User upsert semantics and the implicit local-mode account."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.user import LOCAL_USER_GITHUB_ID, LOCAL_USER_LOGIN
from app.services.oauth_github import GitHubProfile
from app.services.user_service import UserService


def _profile(**overrides) -> GitHubProfile:
    base = {
        "github_user_id": 4242,
        "github_login": "octocat",
        "avatar_url": "https://avatars.example/o.png",
        "display_name": "The Octocat",
        "email": "octocat@example.com",
    }
    return GitHubProfile(**{**base, **overrides})


async def _user_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(User))).scalar_one()


async def test_local_user_is_created_on_demand(session: AsyncSession):
    user = await UserService(session).get_or_create_local_user()
    assert user.github_user_id == LOCAL_USER_GITHUB_ID
    assert user.github_login == LOCAL_USER_LOGIN
    assert user.is_local is True


async def test_local_user_is_reused_not_duplicated(session: AsyncSession):
    service = UserService(session)
    first = await service.get_or_create_local_user()
    second = await service.get_or_create_local_user()
    assert first.id == second.id
    assert await _user_count(session) == 1


async def test_upsert_creates_a_new_user(session: AsyncSession):
    user = await UserService(session).upsert_from_github(_profile())
    assert user.id is not None
    assert user.github_login == "octocat"
    assert user.email == "octocat@example.com"
    assert user.last_login_at is not None
    assert user.is_local is False


async def test_upsert_matches_on_github_id_so_a_rename_updates_in_place(
    session: AsyncSession,
):
    """GitHub logins can be renamed; ids cannot. A rename must not create a
    second account."""
    service = UserService(session)
    original = await service.upsert_from_github(_profile(github_login="octocat"))
    renamed = await service.upsert_from_github(_profile(github_login="mona"))

    assert renamed.id == original.id
    assert renamed.github_login == "mona"
    assert await _user_count(session) == 1


async def test_upsert_refreshes_profile_fields(session: AsyncSession):
    service = UserService(session)
    await service.upsert_from_github(_profile(display_name="Old", email=None))
    updated = await service.upsert_from_github(
        _profile(display_name="New", email="new@example.com")
    )
    assert updated.display_name == "New"
    assert updated.email == "new@example.com"


async def test_upsert_records_each_login(session: AsyncSession):
    service = UserService(session)
    first = await service.upsert_from_github(_profile())
    first_login_at = first.last_login_at
    second = await service.upsert_from_github(_profile())
    assert second.last_login_at >= first_login_at


async def test_different_github_ids_are_different_users(session: AsyncSession):
    service = UserService(session)
    await service.upsert_from_github(_profile(github_user_id=1, github_login="a"))
    await service.upsert_from_github(_profile(github_user_id=2, github_login="b"))
    assert await _user_count(session) == 2


async def test_get_by_github_user_id_finds_nothing_for_unknown(session: AsyncSession):
    assert await UserService(session).get_by_github_user_id(999) is None
