"""User lookup and upsert.

Identity is matched on `github_user_id`, never on login: GitHub logins can be
renamed, ids cannot. A rename therefore updates the existing row instead of
creating a second account.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import LOCAL_USER_GITHUB_ID, LOCAL_USER_LOGIN, User
from app.services.oauth_github import GitHubProfile


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_github_user_id(self, github_user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.github_user_id == github_user_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create_local_user(self) -> User:
        """The implicit account every AUTH_MODE=local request runs as.

        Created on demand rather than seeded by a migration, so tests (which
        build the schema with create_all) and production take the same path.
        """
        existing = await self.get_by_github_user_id(LOCAL_USER_GITHUB_ID)
        if existing is not None:
            return existing
        user = User(
            github_user_id=LOCAL_USER_GITHUB_ID,
            github_login=LOCAL_USER_LOGIN,
            display_name="Local User",
        )
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError:
            # Concurrent first requests raced; the other one won.
            await self.session.rollback()
            existing = await self.get_by_github_user_id(LOCAL_USER_GITHUB_ID)
            if existing is None:
                raise
            return existing
        await self.session.refresh(user)
        return user

    async def upsert_from_github(self, profile: GitHubProfile) -> User:
        """Create or refresh a user from a freshly-read GitHub profile."""
        user = await self.get_by_github_user_id(profile.github_user_id)
        now = datetime.now(timezone.utc)
        if user is None:
            user = User(github_user_id=profile.github_user_id)
            self.session.add(user)
        user.github_login = profile.github_login
        user.avatar_url = profile.avatar_url
        user.display_name = profile.display_name
        user.email = profile.email
        user.last_login_at = now
        await self.session.commit()
        await self.session.refresh(user)
        return user
