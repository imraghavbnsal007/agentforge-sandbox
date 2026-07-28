"""Repository listing and installation-based registration over HTTP."""

import pytest
from httpx import AsyncClient
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


@pytest.fixture
def github_app_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_client_id", "cid")
    monkeypatch.setattr(settings, "github_app_client_secret", "secret")
    monkeypatch.setattr(settings, "github_app_name", "agentforge-dev")
    monkeypatch.setattr(settings, "github_app_id", "1")
    monkeypatch.setattr(settings, "github_app_private_key_path", "/tmp/k.pem")


async def _grant(
    session: AsyncSession,
    user: User,
    repo_id: int = 900,
    full_name: str = "octocat/hello",
    **repo_kw,
) -> GitHubInstallationRepository:
    """Give `user` an installation that grants one repository."""
    installation = (
        await session.execute(
            __import__("sqlalchemy").select(GitHubInstallation)
        )
    ).scalars().first()
    if installation is None:
        installation = GitHubInstallation(
            github_installation_id=500, account_id=1, account_login="octocat"
        )
        session.add(installation)
        await session.commit()
        await session.refresh(installation)
        session.add(
            UserGitHubInstallation(user_id=user.id, installation_id=installation.id)
        )
        await session.commit()

    owner, _, name = full_name.partition("/")
    repository = GitHubInstallationRepository(
        installation_id=installation.id,
        github_repository_id=repo_id,
        owner=owner,
        name=name,
        full_name=full_name,
        default_branch=repo_kw.pop("default_branch", "main"),
        private=repo_kw.pop("private", False),
        archived=repo_kw.pop("archived", False),
        disabled=repo_kw.pop("disabled", False),
    )
    session.add(repository)
    await session.commit()
    await session.refresh(repository)
    return repository


# -- listing ----------------------------------------------------------------


async def test_listing_is_empty_without_installations(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    client, _ = signed_in
    body = (await client.get("/api/v1/repositories")).json()
    assert body["repositories"] == []
    assert body["has_installations"] is False
    assert body["install_url"].endswith("/apps/agentforge-dev/installations/new")


async def test_listing_returns_granted_repositories(
    signed_in: tuple[AsyncClient, User], session: AsyncSession, github_app_mode
):
    client, user = signed_in
    await _grant(session, user)

    body = (await client.get("/api/v1/repositories")).json()
    assert body["has_installations"] is True
    assert len(body["repositories"]) == 1
    entry = body["repositories"][0]
    assert entry["full_name"] == "octocat/hello"
    assert entry["is_registered"] is False
    assert entry["installation_account"] == "octocat"


async def test_listing_marks_registered_repositories(
    signed_in: tuple[AsyncClient, User], session: AsyncSession, github_app_mode
):
    client, user = signed_in
    await _grant(session, user)
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

    entry = (await client.get("/api/v1/repositories")).json()["repositories"][0]
    assert entry["is_registered"] is True
    assert entry["project_id"] == project.id


async def test_listing_requires_authentication(
    client: AsyncClient, github_app_mode
):
    assert (await client.get("/api/v1/repositories")).status_code == 401


# -- registration -----------------------------------------------------------


async def test_registering_a_granted_repository_creates_the_project(
    signed_in: tuple[AsyncClient, User], session: AsyncSession, github_app_mode
):
    client, user = signed_in
    await _grant(session, user)

    response = await client.post(
        "/api/v1/repositories/register", json={"github_repository_id": 900}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "octocat/hello"
    assert body["github_owner"] == "octocat"
    assert body["repo_url"] == "https://github.com/octocat/hello.git"


async def test_registering_an_ungranted_repository_is_refused(
    signed_in: tuple[AsyncClient, User], session: AsyncSession, github_app_mode
):
    """A caller cannot register by inventing a repository id."""
    client, user = signed_in
    await _grant(session, user)

    response = await client.post(
        "/api/v1/repositories/register", json={"github_repository_id": 999999}
    )
    assert response.status_code == 403
    assert "not available" in response.json()["detail"]

    from sqlalchemy import func, select

    count = (
        await session.execute(select(func.count()).select_from(Project))
    ).scalar_one()
    assert count == 0


async def test_registering_another_users_repository_is_refused(
    signed_in: tuple[AsyncClient, User], session: AsyncSession, github_app_mode
):
    client, user = signed_in
    other = User(github_user_id=7777, github_login="mallory")
    session.add(other)
    await session.commit()
    await session.refresh(other)
    await _grant(session, other, repo_id=901, full_name="mallory/secret")

    response = await client.post(
        "/api/v1/repositories/register", json={"github_repository_id": 901}
    )
    assert response.status_code == 403
    assert "mallory/secret" not in response.text


async def test_registering_the_same_repository_twice_conflicts(
    signed_in: tuple[AsyncClient, User], session: AsyncSession, github_app_mode
):
    client, user = signed_in
    await _grant(session, user)
    await client.post(
        "/api/v1/repositories/register", json={"github_repository_id": 900}
    )
    second = await client.post(
        "/api/v1/repositories/register", json={"github_repository_id": 900}
    )
    assert second.status_code == 409


@pytest.mark.parametrize("flag", ["archived", "disabled"])
async def test_registering_an_unusable_repository_is_refused(
    signed_in: tuple[AsyncClient, User],
    session: AsyncSession,
    github_app_mode,
    flag: str,
):
    client, user = signed_in
    await _grant(session, user, **{flag: True})

    response = await client.post(
        "/api/v1/repositories/register", json={"github_repository_id": 900}
    )
    assert response.status_code == 403
    assert flag in response.json()["detail"]


# -- URL registration is closed in github_app mode -------------------------


async def test_url_registration_is_refused_in_github_app_mode(
    signed_in: tuple[AsyncClient, User], github_app_mode
):
    """Accepting a URL would bypass installation grants entirely."""
    client, _ = signed_in
    response = await client.post(
        "/api/v1/projects/register",
        json={"repo_url": "https://github.com/evil/repo", "default_branch": "main"},
    )
    assert response.status_code == 422
    assert "installations" in response.json()["detail"]


async def test_url_registration_still_works_in_local_mode(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """The original single-user workflow is untouched."""
    from app.services.git_client import GitClient

    async def fake_ls_remote(self, repo_url: str, branch: str) -> None:
        return None

    monkeypatch.setattr(GitClient, "ls_remote", fake_ls_remote)

    response = await client.post(
        "/api/v1/projects/register",
        json={
            "repo_url": "https://github.com/acme/widget",
            "default_branch": "main",
        },
    )
    assert response.status_code == 201
    assert response.json()["name"] == "acme/widget"
