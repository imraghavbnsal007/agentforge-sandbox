from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.stub_runner import StubAgentRunner
from app.models import Project, Task
from app.services.run_service import RunService
from tests.conftest import FakeQueue


async def test_create_task_enqueues_job(
    client: AsyncClient, project: Project, fake_queue: FakeQueue
) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={
            "project_id": project.id,
            "title": "Add multiply",
            "request": "Add multiply(a, b).",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert fake_queue.enqueued == [body["id"]]


async def test_create_task_unknown_project_404(
    client: AsyncClient, fake_queue: FakeQueue
) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={"project_id": 999, "title": "Nope", "request": "Nope."},
    )
    assert response.status_code == 404
    assert fake_queue.enqueued == []


async def test_list_tasks(client: AsyncClient, task: Task) -> None:
    response = await client.get("/api/v1/tasks")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["title"] == task.title


async def test_list_tasks_filters_by_project(client: AsyncClient, task: Task) -> None:
    response = await client.get("/api/v1/tasks", params={"project_id": task.project_id})
    assert len(response.json()) == 1
    response = await client.get("/api/v1/tasks", params={"project_id": 999})
    assert response.json() == []


async def test_get_task_detail_without_run(client: AsyncClient, task: Task) -> None:
    response = await client.get(f"/api/v1/tasks/{task.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["request"] == task.request
    assert body["latest_run"] is None


async def test_get_task_detail_includes_latest_run(
    client: AsyncClient, session: AsyncSession, task: Task
) -> None:
    await RunService(session, runner=StubAgentRunner(delay=0)).execute_agent_run(task.id)

    response = await client.get(f"/api/v1/tasks/{task.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    run = body["latest_run"]
    assert run["status"] == "completed"
    assert len(run["plan"]) == 5
    assert len(run["file_changes"]) == 1
    assert run["file_changes"][0]["path"] == "sample_repo/calculator.py"
    assert len(run["test_results"]) == 1
    assert run["test_results"][0]["passed"] == 12
    assert "Files changed" in run["summary"]


async def test_get_unknown_task_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/999")
    assert response.status_code == 404
