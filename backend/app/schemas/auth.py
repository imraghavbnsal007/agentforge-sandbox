from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import AuthMode


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    github_login: str
    display_name: str | None = None
    avatar_url: str | None = None
    email: str | None = None
    is_local: bool = False
    last_login_at: datetime | None = None


class AuthStatus(BaseModel):
    """What the frontend needs to render the right shell: who is signed in,
    which mode the server runs in, and whether sign-in is even possible."""

    auth_mode: AuthMode
    authenticated: bool
    login_available: bool
    user: UserRead | None = None
