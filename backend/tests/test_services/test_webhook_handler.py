"""Applying webhook events to cached installation and repository state.

Each action is asserted to be idempotent: running the same delivery twice
converges rather than compounding, which is what makes a lost dedup ledger a
bounded problem.
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
from app.services.webhook_handler import WebhookHandler


def _installation_block(installation_id: int = 500) -> dict:
    return {
        "id": installation_id,
        "account": {"id": 1, "login": "octocat", "type": "User"},
        "target_type": "User",
        "repository_selection": "selected",
    }


def _repo(repo_id: int = 900, full_name: str = "octocat/hello", **extra) -> dict:
    owner, _, name = full_name.partition("/")
    return {
        "id": repo_id,
        "name": name,
        "full_name": full_name,
        "owner": {"login": owner},
        "default_branch": "main",
        "private": False,
        "archived": False,
        "disabled": False,
        **extra,
    }


async def _existing_installation(
    session: AsyncSession, installation_id: int = 500, **kw
) -> GitHubInstallation:
    installation = GitHubInstallation(
        github_installation_id=installation_id,
        account_id=1,
        account_login="octocat",
        **kw,
    )
    session.add(installation)
    await session.commit()
    await session.refresh(installation)
    return installation


async def _repo_count(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(GitHubInstallationRepository)
        )
    ).scalar_one()


# -- installation.created ---------------------------------------------------


async def test_created_stores_the_installation(session: AsyncSession):
    changed = await WebhookHandler(session).handle(
        "installation",
        {"action": "created", "installation": _installation_block()},
    )
    assert changed is True
    installation = await WebhookHandler(session).installations.get_by_github_id(500)
    assert installation.account_login == "octocat"
    assert installation.is_active is True


async def test_created_seeds_the_repository_cache(session: AsyncSession):
    await WebhookHandler(session).handle(
        "installation",
        {
            "action": "created",
            "installation": _installation_block(),
            "repositories": [_repo(900), _repo(901, "octocat/second")],
        },
    )
    assert await _repo_count(session) == 2


async def test_created_is_idempotent(session: AsyncSession):
    payload = {
        "action": "created",
        "installation": _installation_block(),
        "repositories": [_repo(900)],
    }
    await WebhookHandler(session).handle("installation", payload)
    await WebhookHandler(session).handle("installation", payload)

    installations = (
        await session.execute(select(func.count()).select_from(GitHubInstallation))
    ).scalar_one()
    assert installations == 1
    assert await _repo_count(session) == 1


# -- installation.suspend / unsuspend --------------------------------------


async def test_suspend_marks_the_installation(session: AsyncSession):
    await _existing_installation(session)
    changed = await WebhookHandler(session).handle(
        "installation",
        {"action": "suspend", "installation": _installation_block()},
    )
    assert changed is True
    installation = await WebhookHandler(session).installations.get_by_github_id(500)
    assert installation.is_suspended is True
    assert installation.is_active is False


async def test_unsuspend_restores_access(session: AsyncSession):
    from datetime import datetime, timezone

    await _existing_installation(session, suspended_at=datetime.now(timezone.utc))
    await WebhookHandler(session).handle(
        "installation",
        {"action": "unsuspend", "installation": _installation_block()},
    )
    installation = await WebhookHandler(session).installations.get_by_github_id(500)
    assert installation.is_suspended is False
    assert installation.is_active is True


async def test_suspend_is_idempotent(session: AsyncSession):
    await _existing_installation(session)
    payload = {"action": "suspend", "installation": _installation_block()}
    await WebhookHandler(session).handle("installation", payload)
    first = (await WebhookHandler(session).installations.get_by_github_id(500)).suspended_at
    await WebhookHandler(session).handle("installation", payload)
    installation = await WebhookHandler(session).installations.get_by_github_id(500)
    # Set-to-value, so the state is the same even if the timestamp refreshes.
    assert installation.is_suspended is True and first is not None


async def test_suspend_for_an_unknown_installation_is_a_no_op(
    session: AsyncSession,
):
    changed = await WebhookHandler(session).handle(
        "installation",
        {"action": "suspend", "installation": _installation_block(4242)},
    )
    assert changed is False


# -- installation.deleted ---------------------------------------------------


async def test_deleted_revokes_and_clears_the_grants(session: AsyncSession):
    installation = await _existing_installation(session)
    session.add(
        GitHubInstallationRepository(
            installation_id=installation.id,
            github_repository_id=900,
            owner="octocat",
            name="hello",
            full_name="octocat/hello",
            default_branch="main",
        )
    )
    await session.commit()

    await WebhookHandler(session).handle(
        "installation",
        {"action": "deleted", "installation": _installation_block()},
    )

    refreshed = await WebhookHandler(session).installations.get_by_github_id(500)
    assert refreshed.is_revoked is True
    assert refreshed.is_active is False
    assert await _repo_count(session) == 0


async def test_deleted_preserves_history(session: AsyncSession):
    """Access is withdrawn; tasks, runs and analyses must survive."""
    installation = await _existing_installation(session)
    user = User(github_user_id=1, github_login="octocat")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    session.add(
        UserGitHubInstallation(user_id=user.id, installation_id=installation.id)
    )
    project = Project(
        user_id=user.id,
        name="octocat/hello",
        description="",
        repo_path="",
        github_installation_id=installation.id,
        github_repository_id=900,
    )
    session.add(project)
    await session.commit()

    await WebhookHandler(session).handle(
        "installation",
        {"action": "deleted", "installation": _installation_block()},
    )

    # The installation row and the project both survive.
    assert await WebhookHandler(session).installations.get_by_github_id(500) is not None
    surviving = (
        await session.execute(select(func.count()).select_from(Project))
    ).scalar_one()
    assert surviving == 1


async def test_deleted_is_idempotent(session: AsyncSession):
    await _existing_installation(session)
    payload = {"action": "deleted", "installation": _installation_block()}
    await WebhookHandler(session).handle("installation", payload)
    await WebhookHandler(session).handle("installation", payload)
    installation = await WebhookHandler(session).installations.get_by_github_id(500)
    assert installation.is_revoked is True


# -- installation_repositories ---------------------------------------------


async def test_repositories_added(session: AsyncSession):
    await _existing_installation(session)
    changed = await WebhookHandler(session).handle(
        "installation_repositories",
        {
            "action": "added",
            "installation": _installation_block(),
            "repositories_added": [_repo(900), _repo(901, "octocat/second")],
        },
    )
    assert changed is True
    assert await _repo_count(session) == 2


async def test_repositories_added_is_idempotent(session: AsyncSession):
    await _existing_installation(session)
    payload = {
        "action": "added",
        "installation": _installation_block(),
        "repositories_added": [_repo(900)],
    }
    await WebhookHandler(session).handle("installation_repositories", payload)
    await WebhookHandler(session).handle("installation_repositories", payload)
    assert await _repo_count(session) == 1


async def test_repositories_removed(session: AsyncSession):
    installation = await _existing_installation(session)
    session.add(
        GitHubInstallationRepository(
            installation_id=installation.id,
            github_repository_id=900,
            owner="octocat",
            name="hello",
            full_name="octocat/hello",
            default_branch="main",
        )
    )
    await session.commit()

    changed = await WebhookHandler(session).handle(
        "installation_repositories",
        {
            "action": "removed",
            "installation": _installation_block(),
            "repositories_removed": [{"id": 900}],
        },
    )
    assert changed is True
    assert await _repo_count(session) == 0


async def test_repositories_removed_is_idempotent(session: AsyncSession):
    await _existing_installation(session)
    payload = {
        "action": "removed",
        "installation": _installation_block(),
        "repositories_removed": [{"id": 900}],
    }
    await WebhookHandler(session).handle("installation_repositories", payload)
    await WebhookHandler(session).handle("installation_repositories", payload)
    assert await _repo_count(session) == 0


async def test_removal_only_touches_the_named_repositories(
    session: AsyncSession,
):
    installation = await _existing_installation(session)
    for repo_id, full_name in ((900, "octocat/a"), (901, "octocat/b")):
        session.add(
            GitHubInstallationRepository(
                installation_id=installation.id,
                github_repository_id=repo_id,
                owner="octocat",
                name=full_name.split("/")[1],
                full_name=full_name,
                default_branch="main",
            )
        )
    await session.commit()

    await WebhookHandler(session).handle(
        "installation_repositories",
        {
            "action": "removed",
            "installation": _installation_block(),
            "repositories_removed": [{"id": 900}],
        },
    )

    remaining = (
        await session.execute(select(GitHubInstallationRepository))
    ).scalars().all()
    assert [r.github_repository_id for r in remaining] == [901]


async def test_repository_event_for_unknown_installation_is_a_no_op(
    session: AsyncSession,
):
    changed = await WebhookHandler(session).handle(
        "installation_repositories",
        {
            "action": "added",
            "installation": _installation_block(4242),
            "repositories_added": [_repo(900)],
        },
    )
    assert changed is False
    assert await _repo_count(session) == 0


# -- unsupported input ------------------------------------------------------


@pytest.mark.parametrize(
    "event,payload",
    [
        ("ping", {"zen": "hello"}),
        ("pull_request", {"action": "opened"}),
        ("installation", {"action": "unknown_action"}),
        ("installation_repositories", {"action": "unknown_action"}),
        ("installation", {"action": "created"}),  # no installation block
    ],
)
async def test_unsupported_input_changes_nothing(
    session: AsyncSession, event: str, payload: dict
):
    assert await WebhookHandler(session).handle(event, payload) is False


async def test_malformed_repository_entries_are_skipped(session: AsyncSession):
    await _existing_installation(session)
    await WebhookHandler(session).handle(
        "installation_repositories",
        {
            "action": "added",
            "installation": _installation_block(),
            "repositories_added": [{"no_id": True}, _repo(900)],
        },
    )
    assert await _repo_count(session) == 1


# -- integration with credential resolution ---------------------------------


async def test_revocation_webhook_blocks_the_next_repository_operation(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """The whole point of handling installation.deleted: the very next clone
    must be refused, without waiting for a manual refresh."""
    from app.core.config import settings
    from app.core.enums import AuthMode
    from app.services.github_credentials import (
        GitHubCredentialResolver,
        RepoOperation,
        RepositoryAccessError,
    )

    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_commit_name", "AgentForge[bot]")
    monkeypatch.setattr(settings, "github_app_commit_email", "bot@example.com")

    installation = await _existing_installation(session)
    user = User(github_user_id=1, github_login="octocat")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    session.add(
        UserGitHubInstallation(user_id=user.id, installation_id=installation.id)
    )
    session.add(
        GitHubInstallationRepository(
            installation_id=installation.id,
            github_repository_id=900,
            owner="octocat",
            name="hello",
            full_name="octocat/hello",
            default_branch="main",
        )
    )
    project = Project(
        user_id=user.id,
        name="octocat/hello",
        description="",
        repo_path="",
        repo_url="https://github.com/octocat/hello.git",
        github_owner="octocat",
        github_repo="hello",
        github_installation_id=installation.id,
        github_repository_id=900,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    from tests.test_services.test_github_credentials import FakeTokenService

    resolver = GitHubCredentialResolver(session, FakeTokenService())
    # Access works before the webhook.
    assert await resolver.resolve(
        project.id, RepoOperation.clone, user_id=user.id
    )

    await WebhookHandler(session).handle(
        "installation",
        {"action": "deleted", "installation": _installation_block()},
    )

    with pytest.raises(RepositoryAccessError, match="no longer available"):
        await resolver.resolve(project.id, RepoOperation.clone, user_id=user.id)


async def test_suspension_webhook_blocks_the_next_repository_operation(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    from app.core.config import settings
    from app.core.enums import AuthMode
    from app.services.github_credentials import (
        GitHubCredentialResolver,
        RepoOperation,
        RepositoryAccessError,
    )

    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_commit_name", "AgentForge[bot]")
    monkeypatch.setattr(settings, "github_app_commit_email", "bot@example.com")

    installation = await _existing_installation(session)
    user = User(github_user_id=1, github_login="octocat")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    session.add(
        UserGitHubInstallation(user_id=user.id, installation_id=installation.id)
    )
    session.add(
        GitHubInstallationRepository(
            installation_id=installation.id,
            github_repository_id=900,
            owner="octocat",
            name="hello",
            full_name="octocat/hello",
            default_branch="main",
        )
    )
    project = Project(
        user_id=user.id, name="octocat/hello", description="", repo_path="",
        repo_url="https://github.com/octocat/hello.git",
        github_owner="octocat", github_repo="hello",
        github_installation_id=installation.id, github_repository_id=900,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)

    from tests.test_services.test_github_credentials import FakeTokenService

    await WebhookHandler(session).handle(
        "installation",
        {"action": "suspend", "installation": _installation_block()},
    )

    resolver = GitHubCredentialResolver(session, FakeTokenService())
    with pytest.raises(RepositoryAccessError):
        await resolver.resolve(project.id, RepoOperation.clone, user_id=user.id)
