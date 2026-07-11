from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.mock_runner import MockRunner
from app.models import Project, Task
from app.services.run_service import RunService
from tests.conftest import FakeQueue
from tests.test_services.test_run_service import FakeExecutor


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
    await RunService(
        session, runner=MockRunner(delay=0), executor=FakeExecutor()
    ).execute_agent_run(task.id)

    response = await client.get(f"/api/v1/tasks/{task.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    run = body["latest_run"]
    assert run["status"] == "completed"
    assert len(run["plan"]) == 4
    paths = [c["path"] for c in run["file_changes"]]
    assert "calculator.py" in paths
    assert "tests/test_multiply.py" in paths
    assert run["file_changes"][0]["diff"].startswith("---")
    assert len(run["test_results"]) == 1
    assert run["test_results"][0]["passed"] == 7
    assert run["test_results"][0]["stderr"] == ""
    assert run["log"] and "workspace ready" in run["log"]
    assert "Files changed" in run["summary"]
    # Mock runs never call LLMService — no llm_runs rows, so these are null.
    assert run["llm_provider"] is None
    assert run["llm_model"] is None


async def test_task_detail_reports_actual_provider_and_model_used(
    client: AsyncClient, session: AsyncSession, task: Task
) -> None:
    """The task page must show the provider/model a run actually used (from
    its llm_runs rows), not the server's global default — this is what
    surfaced the Gemini model-ID normalization bug in the first place."""
    from app.models import LLMRun

    run = await RunService(
        session, runner=MockRunner(delay=0), executor=FakeExecutor()
    ).execute_agent_run(task.id)

    session.add_all(
        [
            LLMRun(
                agent_run_id=run.id, provider="google", model="gemini-2.5-flash",
                phase="planning", success=True,
            ),
            LLMRun(
                agent_run_id=run.id, provider="google", model="gemini-2.5-flash",
                phase="coding", success=True,
            ),
        ]
    )
    await session.commit()

    body = (await client.get(f"/api/v1/tasks/{task.id}")).json()
    latest = body["latest_run"]
    assert latest["llm_provider"] == "google"
    assert latest["llm_model"] == "gemini-2.5-flash"
    # Same info is present in the run history list.
    assert body["runs"][-1]["llm_provider"] == "google"


async def test_get_unknown_task_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/999")
    assert response.status_code == 404


async def test_retry_task_reenqueues(
    client: AsyncClient, session: AsyncSession, task: Task, fake_queue: FakeQueue
) -> None:
    # Simulate a finished (failed or completed) task, then retry it.
    await RunService(
        session, runner=MockRunner(delay=0), executor=FakeExecutor()
    ).execute_agent_run(task.id)

    response = await client.post(f"/api/v1/tasks/{task.id}/retry")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert fake_queue.enqueued == [task.id]

    # A second run accumulates in the history; detail exposes all runs.
    await RunService(
        session, runner=MockRunner(delay=0), executor=FakeExecutor()
    ).execute_agent_run(task.id)
    detail = (await client.get(f"/api/v1/tasks/{task.id}")).json()
    assert len(detail["runs"]) == 2
    assert detail["latest_run"]["id"] == detail["runs"][-1]["id"]
    assert detail["latest_run_mode"] == "mock"


async def test_retry_unknown_task_404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tasks/999/retry")
    assert response.status_code == 404


async def test_list_tasks_includes_latest_run_mode(
    client: AsyncClient, session: AsyncSession, task: Task
) -> None:
    await RunService(
        session, runner=MockRunner(delay=0), executor=FakeExecutor()
    ).execute_agent_run(task.id)
    body = (await client.get("/api/v1/tasks")).json()
    assert body[0]["latest_run_mode"] == "mock"


async def test_approve_and_reject_flow(
    client: AsyncClient, session: AsyncSession, task: Task, fake_queue: FakeQueue
) -> None:
    from app.core.enums import TaskStatus

    # Approve/reject require ready_for_review.
    assert (await client.post(f"/api/v1/tasks/{task.id}/approve")).status_code == 409
    assert (await client.post(f"/api/v1/tasks/{task.id}/reject")).status_code == 409

    task.status = TaskStatus.ready_for_review
    await session.commit()
    response = await client.post(f"/api/v1/tasks/{task.id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "publishing"
    assert fake_queue.publish_enqueued == [task.id]

    # Reject path on a second reviewable task state.
    task.status = TaskStatus.ready_for_review
    await session.commit()
    response = await client.post(f"/api/v1/tasks/{task.id}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    assert (await client.post("/api/v1/tasks/999/approve")).status_code == 404


async def test_config_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    body = response.json()
    assert body["agent_mode"] in ("mock", "llm")
    assert "anthropic_model" in body
    assert isinstance(body["api_key_configured"], bool)
