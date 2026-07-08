from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import InvalidInputError
from app.services.git_client import GitClient, GitError
from app.services.github_config import parse_github_url
from tests.conftest import FakeQueue


def test_parse_github_url_variants():
    assert parse_github_url("https://github.com/acme/widget") == ("acme", "widget")
    assert parse_github_url("https://github.com/acme/widget.git") == ("acme", "widget")
    assert parse_github_url("https://github.com/acme/widget/") == ("acme", "widget")
    assert parse_github_url(" https://github.com/a-b.c/d_e.f ") == ("a-b.c", "d_e.f")


@pytest.mark.parametrize(
    "bad",
    [
        "github.com/acme/widget",
        "https://gitlab.com/acme/widget",
        "https://github.com/acme",
        "https://github.com/acme/widget/tree/main",
        "git@github.com:acme/widget.git",
        "not a url",
    ],
)
def test_parse_github_url_rejects(bad: str):
    with pytest.raises(InvalidInputError):
        parse_github_url(bad)


@pytest.fixture
def ok_ls_remote(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(GitClient, "ls_remote", mock)
    return mock


async def test_register_project(
    client: AsyncClient, fake_queue: FakeQueue, ok_ls_remote: AsyncMock
) -> None:
    response = await client.post(
        "/api/v1/projects/register",
        json={"repo_url": "https://github.com/acme/widget"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "acme/widget"
    assert body["repo_url"] == "https://github.com/acme/widget.git"
    assert body["default_branch"] == "main"
    assert body["github_owner"] == "acme"
    assert body["github_repo"] == "widget"
    assert body["analysis_status"] is None
    ok_ls_remote.assert_awaited_once()
    # Registration is lightweight: nothing enqueued, no analysis row.
    assert fake_queue.analyze_enqueued == []


async def test_register_invalid_url(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/projects/register", json={"repo_url": "https://gitlab.com/a/b"}
    )
    assert response.status_code == 422


async def test_register_allowlist_refusal(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, ok_ls_remote: AsyncMock
) -> None:
    monkeypatch.setattr(settings, "github_allowed_repos", "acme/widget")
    response = await client.post(
        "/api/v1/projects/register", json={"repo_url": "https://github.com/evil/repo"}
    )
    assert response.status_code == 403
    assert "GITHUB_ALLOWED_REPOS" in response.json()["detail"]
    ok_ls_remote.assert_not_awaited()


async def test_register_unreachable_repo(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        GitClient, "ls_remote", AsyncMock(side_effect=GitError("git ls-remote failed"))
    )
    response = await client.post(
        "/api/v1/projects/register", json={"repo_url": "https://github.com/acme/gone"}
    )
    assert response.status_code == 422
    assert "Repository validation failed" in response.json()["detail"]


async def test_register_duplicate(
    client: AsyncClient, ok_ls_remote: AsyncMock
) -> None:
    payload = {"repo_url": "https://github.com/acme/widget"}
    assert (await client.post("/api/v1/projects/register", json=payload)).status_code == 201
    assert (await client.post("/api/v1/projects/register", json=payload)).status_code == 409


async def test_register_duplicate_repo_under_different_name(
    client: AsyncClient, ok_ls_remote: AsyncMock
) -> None:
    # A project created manually (different name) already points at the repo.
    created = await client.post(
        "/api/v1/projects",
        json={
            "name": "My Custom Name",
            "repo_url": "https://github.com/acme/widget.git",
            "github_owner": "acme",
            "github_repo": "widget",
        },
    )
    assert created.status_code == 201
    response = await client.post(
        "/api/v1/projects/register",
        json={"repo_url": "https://github.com/acme/widget"},
    )
    assert response.status_code == 409
    assert "already registered as project" in response.json()["detail"]


async def test_analyze_endpoint_creates_pending_and_enqueues(
    client: AsyncClient, fake_queue: FakeQueue, ok_ls_remote: AsyncMock
) -> None:
    body = (
        await client.post(
            "/api/v1/projects/register",
            json={"repo_url": "https://github.com/acme/widget"},
        )
    ).json()
    pid = body["id"]

    response = await client.post(f"/api/v1/projects/{pid}/analyze")
    assert response.status_code == 200
    analysis = response.json()
    assert analysis["status"] == "pending"
    assert fake_queue.analyze_enqueued == [analysis["id"]]

    # A second trigger while one is pending conflicts.
    assert (await client.post(f"/api/v1/projects/{pid}/analyze")).status_code == 409

    # Project list/detail expose the snapshot.
    listed = (await client.get("/api/v1/projects")).json()
    mine = next(p for p in listed if p["id"] == pid)
    assert mine["analysis_status"] == "pending"
    detail = (await client.get(f"/api/v1/projects/{pid}")).json()
    assert detail["latest_analysis"]["status"] == "pending"


async def test_analyze_sample_project_rejected(
    client: AsyncClient, project
) -> None:
    response = await client.post(f"/api/v1/projects/{project.id}/analyze")
    assert response.status_code == 422


async def test_first_task_triggers_analysis(
    client: AsyncClient, fake_queue: FakeQueue, ok_ls_remote: AsyncMock
) -> None:
    body = (
        await client.post(
            "/api/v1/projects/register",
            json={"repo_url": "https://github.com/acme/widget"},
        )
    ).json()
    pid = body["id"]

    task_payload = {"project_id": pid, "title": "T", "request": "R"}
    assert (await client.post("/api/v1/tasks", json=task_payload)).status_code == 201
    assert len(fake_queue.analyze_enqueued) == 1

    # Second task must not re-trigger analysis.
    assert (await client.post("/api/v1/tasks", json=task_payload)).status_code == 201
    assert len(fake_queue.analyze_enqueued) == 1
