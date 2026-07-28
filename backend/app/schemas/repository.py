from datetime import datetime

from pydantic import BaseModel


class RepositoryRead(BaseModel):
    """A repository the caller's installations grant access to."""

    github_repository_id: int
    owner: str
    name: str
    full_name: str
    default_branch: str
    private: bool
    archived: bool
    disabled: bool
    # Whether it can actually receive a pull request.
    is_usable: bool
    last_synced_at: datetime | None = None

    # Installation context — lets the picker group by account and explain
    # why a repository is unavailable.
    installation_id: int
    installation_account: str
    installation_active: bool

    # Registration state, resolved for this caller only.
    is_registered: bool = False
    project_id: int | None = None


class RepositoryList(BaseModel):
    app_configured: bool
    install_url: str | None = None
    # False when the user has no installations at all — the picker shows the
    # "install the App" empty state rather than "no repositories".
    has_installations: bool = False
    repositories: list[RepositoryRead] = []


class RepositoryRegister(BaseModel):
    """Registration by GitHub repository id only.

    Deliberately not owner/repo or a URL: the id is checked against the
    caller's own installation grants, so there is nothing to forge.
    """

    github_repository_id: int
