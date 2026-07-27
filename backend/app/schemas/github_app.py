from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InstallationRead(BaseModel):
    """An installation as shown to its owner.

    Deliberately excludes anything token-shaped — installation tokens are
    server-side only and never reach the frontend.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    github_installation_id: int
    account_login: str
    account_type: str
    repository_selection: str
    suspended_at: datetime | None = None
    revoked_at: datetime | None = None
    last_synced_at: datetime | None = None
    is_active: bool = True


class InstallationsStatus(BaseModel):
    """Everything the Repositories/Settings screen needs to decide what to
    render: whether the server can talk to GitHub at all, where to send the
    user to install, and what they already have."""

    app_configured: bool
    install_url: str | None = None
    installations: list[InstallationRead] = []
