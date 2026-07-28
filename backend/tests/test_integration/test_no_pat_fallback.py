"""No path in github_app mode reaches the shared personal access token.

These guard the *defensive* branches — the ones that only run when something
unexpected happens, and which would otherwise silently widen the credential
in exactly the situation where that is most dangerous.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AuthMode
from app.models import Project
from app.services.github_credentials import RepositoryAccessError
from app.services.publisher import GitHubPublisher

PAT = "ghp_the_shared_personal_access_token"


@pytest.fixture(autouse=True)
def _pat_configured(monkeypatch: pytest.MonkeyPatch):
    """The PAT is present and valid — it must simply never be reachable."""
    monkeypatch.setattr(settings, "github_token", PAT)


@pytest.fixture
def app_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)


async def test_publisher_default_client_carries_no_credential_in_app_mode(
    app_mode,
):
    """Constructed without a resolver, the fallback client must be empty
    rather than PAT-bearing."""
    publisher = GitHubPublisher()
    assert publisher.git._token == ""


async def test_publisher_default_client_uses_the_pat_in_local_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.local)
    publisher = GitHubPublisher()
    assert publisher.git._token == PAT


async def test_git_client_builder_refuses_without_a_session_in_app_mode(
    session: AsyncSession, app_mode
):
    """No session means no way to resolve an installation credential; that
    must abort rather than degrade."""
    from app.services.github_credentials import RepoOperation
    from app.services.run_service import build_git_client
    from tests.helpers import local_user_id

    project = Project(
        user_id=await local_user_id(session),
        name="acme/widget",
        description="",
        repo_path="",
    )
    session.add(project)
    await session.commit()

    with pytest.raises(RepositoryAccessError, match="no longer available"):
        await build_git_client(project, None, RepoOperation.clone)


async def test_git_client_builder_uses_the_pat_without_a_session_in_local_mode(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    from app.services.github_credentials import RepoOperation
    from app.services.run_service import build_git_client
    from tests.helpers import local_user_id

    monkeypatch.setattr(settings, "auth_mode", AuthMode.local)
    project = Project(
        user_id=await local_user_id(session),
        name="acme/widget",
        description="",
        repo_path="",
    )
    session.add(project)
    await session.commit()

    client = await build_git_client(project, None, RepoOperation.clone)
    assert client._token == PAT


async def test_pull_request_refuses_without_credentials_in_app_mode(
    session: AsyncSession, app_mode
):
    """The PR path must not reach for the PAT when a resolver is absent."""
    from app.core.enums import ChangeType, RunStatus, TaskStatus
    from app.models import AgentRun, FileChange, Task
    from tests.helpers import local_user_id

    project = Project(
        user_id=await local_user_id(session),
        name="acme/widget",
        description="",
        repo_path="",
        repo_url="https://github.com/acme/widget.git",
        default_branch="main",
        github_owner="acme",
        github_repo="widget",
    )
    session.add(project)
    await session.flush()
    task = Task(project_id=project.id, title="T", request="R")
    session.add(task)
    await session.flush()
    run = AgentRun(
        task_id=task.id, mode="llm", status=RunStatus.completed, summary="s",
        file_changes=[
            FileChange(path="a.py", change_type=ChangeType.modify,
                       diff="d", is_binary=False)
        ],
        test_results=[],
    )
    session.add(run)
    await session.commit()

    # No resolver: every credential resolution returns None.
    publisher = GitHubPublisher(executor=None)
    with pytest.raises(RepositoryAccessError, match="no longer available"):
        await publisher._open_pull_request(
            project, task, run, "agentforge/task-1", lambda _m: None
        )
