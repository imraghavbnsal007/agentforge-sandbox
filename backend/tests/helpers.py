"""Shared test helpers."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def make_local_user(session: AsyncSession) -> User:
    """The AUTH_MODE=local account, via the same path the app uses."""
    from app.services.user_service import UserService

    return await UserService(session).get_or_create_local_user()


async def local_user_id(session: AsyncSession) -> int:
    return (await make_local_user(session)).id
