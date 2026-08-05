"""Showcase mode: what a public visitor may and may not do.

The threat is not a confused user, it is a stranger with curl. Hiding
buttons is presentation; these tests cover the enforcement.
"""

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.enums import AgentMode
from app.models import Project, Task


@pytest.fixture
def showcase(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "showcase_mode", True)


# Every route that reaches outside the demonstration: real GitHub writes,
# repository cloning, API spend, or server-side configuration.
GATED = [
    ("post", "/api/v1/projects", {"name": "x", "repo_path": "sample_repo"}),
    ("post", "/api/v1/projects/register", {"repo_url": "https://github.com/a/b.git"}),
    ("post", "/api/v1/repositories/register", {"github_repository_id": 1}),
]


@pytest.mark.parametrize("method,path,body", GATED, ids=[p for _, p, _ in GATED])
async def test_reaching_outside_the_demo_is_refused(
    client: AsyncClient, showcase, method, path, body
):
    response = await getattr(client, method)(path, json=body)
    assert response.status_code == 403
    assert "portfolio demonstration" in response.json()["detail"]


async def test_publishing_to_github_is_refused(
    client: AsyncClient, showcase, task: Task
):
    response = await client.post(f"/api/v1/tasks/{task.id}/approve")
    assert response.status_code == 403


async def test_analysis_is_refused(client: AsyncClient, showcase, project: Project):
    """Analysis clones a repository and spends real API budget."""
    response = await client.post(f"/api/v1/projects/{project.id}/analyze")
    assert response.status_code == 403


async def test_changing_project_ai_settings_is_refused(
    client: AsyncClient, showcase, project: Project
):
    response = await client.patch(
        f"/api/v1/projects/{project.id}/settings",
        json={"preferred_provider": "anthropic"},
    )
    assert response.status_code == 403


# -- what a visitor is still allowed to do ----------------------------------


async def test_a_visitor_can_still_create_a_task(
    client: AsyncClient, showcase, project: Project
):
    """The demonstration is worthless if nothing can be run."""
    response = await client.post(
        "/api/v1/tasks",
        json={"project_id": project.id, "title": "Add multiply", "request": "Please."},
    )
    assert response.status_code == 201


async def test_a_visitor_can_still_read(client: AsyncClient, showcase, task: Task):
    assert (await client.get("/api/v1/tasks")).status_code == 200
    assert (await client.get(f"/api/v1/tasks/{task.id}")).status_code == 200
    assert (await client.get("/api/v1/usage")).status_code == 200


# -- the billing hole -------------------------------------------------------


async def test_showcase_mode_forces_the_mock_agent(monkeypatch: pytest.MonkeyPatch):
    """A visitor must not be able to spend the operator's API budget, whatever
    AGENT_MODE the server was started with."""
    monkeypatch.setattr(settings, "agent_mode", AgentMode.llm)
    monkeypatch.setattr(settings, "showcase_mode", True)
    assert settings.effective_agent_mode() == AgentMode.mock


async def test_normal_mode_leaves_the_agent_alone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "agent_mode", AgentMode.llm)
    monkeypatch.setattr(settings, "showcase_mode", False)
    assert settings.effective_agent_mode() == AgentMode.llm


async def test_the_config_endpoint_advertises_the_mode(client: AsyncClient, showcase):
    """The banner and the hidden controls are driven from this."""
    body = (await client.get("/api/v1/config")).json()
    assert body["showcase_mode"] is True
    assert body["agent_mode"] == "mock"


async def test_nothing_is_gated_when_showcase_mode_is_off(
    client: AsyncClient, project: Project
):
    """The default must be the full product; showcase mode is opt-in."""
    assert settings.showcase_mode is False
    response = await client.patch(
        f"/api/v1/projects/{project.id}/settings",
        json={"preferred_provider": "anthropic"},
    )
    assert response.status_code != 403
