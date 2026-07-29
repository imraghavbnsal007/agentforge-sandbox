"""Cancel, retry and the event/stream endpoints at the HTTP boundary.

Every control here is user-scoped: another user's task is a 404, never a 403.
"""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AuthMode, RunStatus, TaskEventType, TaskStatus
from app.core.security import CSRF_HEADER
from app.models import AgentRun, Project, Task, User
from app.services.kv_store import InMemoryKVStore
from app.services.session_store import SessionStore
from app.services.task_events import TaskEventService


@pytest.fixture
def app_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_client_id", "cid")
    monkeypatch.setattr(settings, "github_app_client_secret", "secret")


async def _sign_in(client: AsyncClient, kv: InMemoryKVStore, user: User) -> None:
    data = await SessionStore(kv, ttl_seconds=3600).create(user.id, user.github_login)
    client.cookies.set(settings.session_cookie_name, data.session_id)
    client.headers[CSRF_HEADER] = data.csrf_token


async def _running_run(session: AsyncSession, task: Task) -> AgentRun:
    run = AgentRun(
        task_id=task.id, mode="mock", status=RunStatus.running,
        file_changes=[], test_results=[],
    )
    session.add(run)
    task.status = TaskStatus.coding
    await session.commit()
    await session.refresh(run)
    return run


# -- cancel -----------------------------------------------------------------


async def test_cancelling_a_queued_task_cancels_it_outright(
    client: AsyncClient, session: AsyncSession, task: Task
):
    """Nothing is running, so no checkpoint will ever be reached."""
    response = await client.post(f"/api/v1/tasks/{task.id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_cancelling_a_running_task_requests_a_stop(
    client: AsyncClient, session: AsyncSession, task: Task, kv: InMemoryKVStore
):
    """The task stays running until the worker reaches a checkpoint."""
    run = await _running_run(session, task)

    response = await client.post(f"/api/v1/tasks/{task.id}/cancel")
    assert response.status_code == 200
    # Still coding — the worker has not stopped yet.
    assert response.json()["status"] == "coding"

    await session.refresh(run)
    assert run.cancel_requested_at is not None
    # And the signal is in the KV store for promptness.
    from app.services.execution_lock import CancellationSignal

    assert await CancellationSignal(kv).is_requested(task.id) is True


async def test_cancellation_is_recorded_durably_as_well_as_in_redis(
    client: AsyncClient, session: AsyncSession, task: Task
):
    """A Redis restart must not lose a cancellation request."""
    run = await _running_run(session, task)
    await client.post(f"/api/v1/tasks/{task.id}/cancel")
    await session.refresh(run)
    assert run.cancel_requested_at is not None


async def test_cancelling_a_completed_task_is_refused(
    client: AsyncClient, session: AsyncSession, task: Task
):
    task.status = TaskStatus.completed
    await session.commit()
    response = await client.post(f"/api/v1/tasks/{task.id}/cancel")
    assert response.status_code == 409
    assert "cannot be cancelled" in response.json()["detail"]


async def test_cancelling_an_unknown_task_is_404(client: AsyncClient):
    assert (await client.post("/api/v1/tasks/9999/cancel")).status_code == 404


# -- events -----------------------------------------------------------------


async def test_event_history_is_returned_in_order(
    client: AsyncClient, session: AsyncSession, task: Task, kv: InMemoryKVStore
):
    run = await _running_run(session, task)
    service = TaskEventService(session, kv)
    for i in range(3):
        await service.emit(
            task, TaskEventType.stage_changed, run=run, message=f"m{i}", user_id=1
        )

    body = (await client.get(f"/api/v1/tasks/{task.id}/events")).json()
    assert [e["message"] for e in body["events"]] == ["m0", "m1", "m2"]
    assert [e["sequence_number"] for e in body["events"]] == [1, 2, 3]


async def test_event_history_supports_a_cursor(
    client: AsyncClient, session: AsyncSession, task: Task, kv: InMemoryKVStore
):
    run = await _running_run(session, task)
    service = TaskEventService(session, kv)
    created = [
        await service.emit(task, TaskEventType.progress, run=run, user_id=1)
        for _ in range(4)
    ]

    body = (
        await client.get(
            f"/api/v1/tasks/{task.id}/events?after_id={created[1].id}"
        )
    ).json()
    assert len(body["events"]) == 2


async def test_event_history_paginates(
    client: AsyncClient, session: AsyncSession, task: Task, kv: InMemoryKVStore
):
    run = await _running_run(session, task)
    service = TaskEventService(session, kv)
    for _ in range(5):
        await service.emit(task, TaskEventType.progress, run=run, user_id=1)

    body = (await client.get(f"/api/v1/tasks/{task.id}/events?limit=2")).json()
    assert len(body["events"]) == 2
    assert body["next_cursor"] is not None


async def test_events_for_an_unknown_task_are_404(client: AsyncClient):
    assert (await client.get("/api/v1/tasks/9999/events")).status_code == 404


# -- cross-user isolation ---------------------------------------------------


@pytest.fixture
async def other_users_task(session: AsyncSession) -> tuple[User, User, Task]:
    alice = User(github_user_id=1, github_login="alice")
    bob = User(github_user_id=2, github_login="bob")
    session.add_all([alice, bob])
    await session.commit()
    await session.refresh(alice)
    await session.refresh(bob)

    project = Project(
        user_id=alice.id, name="alice/repo", description="", repo_path="sample_repo"
    )
    session.add(project)
    await session.flush()
    task = Task(project_id=project.id, title="Alice's", request="private")
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return alice, bob, task


@pytest.mark.parametrize("action", ["cancel", "retry"])
async def test_another_user_cannot_control_your_task(
    client: AsyncClient,
    kv: InMemoryKVStore,
    other_users_task,
    app_mode,
    action: str,
):
    _, bob, task = other_users_task
    await _sign_in(client, kv, bob)
    response = await client.post(f"/api/v1/tasks/{task.id}/{action}")
    assert response.status_code == 404


async def test_another_user_cannot_read_your_events(
    client: AsyncClient, kv: InMemoryKVStore, other_users_task, app_mode
):
    _, bob, task = other_users_task
    await _sign_in(client, kv, bob)
    assert (
        await client.get(f"/api/v1/tasks/{task.id}/events")
    ).status_code == 404


async def test_another_user_cannot_open_your_stream(
    client: AsyncClient, kv: InMemoryKVStore, other_users_task, app_mode
):
    _, bob, task = other_users_task
    await _sign_in(client, kv, bob)
    assert (
        await client.get(f"/api/v1/tasks/{task.id}/stream")
    ).status_code == 404


async def test_the_owner_can_read_their_own_events(
    client: AsyncClient, kv: InMemoryKVStore, other_users_task, app_mode
):
    alice, _, task = other_users_task
    await _sign_in(client, kv, alice)
    assert (
        await client.get(f"/api/v1/tasks/{task.id}/events")
    ).status_code == 200


# -- secret hygiene over the wire ------------------------------------------


async def test_no_token_reaches_the_events_endpoint(
    client: AsyncClient, session: AsyncSession, task: Task, kv: InMemoryKVStore
):
    token = "ghs_installation_token_value"
    run = await _running_run(session, task)
    await TaskEventService(session, kv).emit(
        task,
        TaskEventType.warning,
        run=run,
        user_id=1,
        message=f"failed with {token}",
        metadata={"token": token},
    )
    response = await client.get(f"/api/v1/tasks/{task.id}/events")
    assert token not in response.text


# -- run again as a new task ------------------------------------------------


async def test_a_completed_task_can_be_run_again_as_a_new_task(
    client: AsyncClient, session: AsyncSession, task: Task, fake_queue
):
    """Completed stays terminal; repeating the work means a new task."""
    task.status = TaskStatus.completed
    await session.commit()

    response = await client.post(f"/api/v1/tasks/{task.id}/duplicate")

    assert response.status_code == 201
    created = response.json()
    assert created["id"] != task.id
    assert created["title"] == task.title
    assert created["request"] == task.request
    assert created["project_id"] == task.project_id
    assert created["status"] == "pending"
    assert fake_queue.enqueued == [created["id"]]


async def test_running_again_preserves_the_original(
    client: AsyncClient, session: AsyncSession, task: Task
):
    task.status = TaskStatus.completed
    await session.commit()

    await client.post(f"/api/v1/tasks/{task.id}/duplicate")

    await session.refresh(task)
    assert task.status == TaskStatus.completed


async def test_running_again_copies_the_model_choices(
    client: AsyncClient, session: AsyncSession, task: Task
):
    task.status = TaskStatus.completed
    task.llm_provider = "google"
    task.llm_model = "gemini-3.1-flash-lite"
    task.execution_profile = "cheap"
    await session.commit()

    created = (await client.post(f"/api/v1/tasks/{task.id}/duplicate")).json()

    assert created["llm_provider"] == "google"
    assert created["llm_model"] == "gemini-3.1-flash-lite"
    assert created["execution_profile"] == "cheap"


async def test_running_again_starts_with_no_run_history(
    client: AsyncClient, session: AsyncSession, task: Task
):
    """The new task must not inherit the old workspace or runs."""
    task.status = TaskStatus.completed
    await session.commit()

    created = (await client.post(f"/api/v1/tasks/{task.id}/duplicate")).json()
    detail = (await client.get(f"/api/v1/tasks/{created['id']}")).json()

    assert detail["runs"] == []
    assert detail["latest_run"] is None


async def test_running_again_is_scoped_to_the_owner(
    client: AsyncClient, kv: InMemoryKVStore, other_users_task, app_mode
):
    _, bob, task = other_users_task
    await _sign_in(client, kv, bob)
    assert (
        await client.post(f"/api/v1/tasks/{task.id}/duplicate")
    ).status_code == 404


async def test_running_again_an_unknown_task_is_404(client: AsyncClient):
    assert (await client.post("/api/v1/tasks/9999/duplicate")).status_code == 404


# -- deletion ---------------------------------------------------------------


async def test_deleting_a_task_removes_it(
    client: AsyncClient, session: AsyncSession, task: Task
):
    response = await client.delete(f"/api/v1/tasks/{task.id}")
    assert response.status_code == 204
    assert (await client.get(f"/api/v1/tasks/{task.id}")).status_code == 404
    assert (await client.get("/api/v1/tasks")).json() == []


async def test_deleting_a_task_removes_its_runs_and_artifacts(
    client: AsyncClient, session: AsyncSession, task: Task
):
    from sqlalchemy import func, select

    from app.core.enums import ChangeType, RunStatus
    from app.models import FileChange, TestResult

    run = AgentRun(
        task_id=task.id, mode="mock", status=RunStatus.completed,
        file_changes=[
            FileChange(path="a.py", change_type=ChangeType.modify,
                       diff="d", is_binary=False)
        ],
        test_results=[
            TestResult(suite="pytest", passed=1, failed=0, errored=0,
                       duration=0.1, output="ok", stderr="")
        ],
    )
    session.add(run)
    await session.commit()

    await client.delete(f"/api/v1/tasks/{task.id}")

    for model in (AgentRun, FileChange, TestResult):
        remaining = (
            await session.execute(select(func.count()).select_from(model))
        ).scalar_one()
        assert remaining == 0, model.__name__


async def test_deleting_a_task_preserves_usage_and_cost_records(
    client: AsyncClient, session: AsyncSession, task: Task
):
    """The Usage page must stay accurate — deleting a task must not quietly
    reduce reported spend."""
    from sqlalchemy import select

    from app.core.enums import RunStatus
    from app.models import LLMRun

    run = AgentRun(task_id=task.id, mode="llm", status=RunStatus.completed,
                   file_changes=[], test_results=[])
    session.add(run)
    await session.commit()
    await session.refresh(run)
    session.add(
        LLMRun(
            agent_run_id=run.id, project_id=task.project_id,
            provider="google", model="gemini-3.1-flash-lite", phase="coding",
            tokens_in=100, tokens_out=20, estimated_cost=0.005, success=True,
        )
    )
    await session.commit()

    await client.delete(f"/api/v1/tasks/{task.id}")

    surviving = (await session.execute(select(LLMRun))).scalars().all()
    assert len(surviving) == 1
    assert surviving[0].estimated_cost == 0.005
    assert surviving[0].project_id == task.project_id
    # Only the link to the deleted run is cleared.
    assert surviving[0].agent_run_id is None


async def test_deleting_one_task_never_affects_another(
    client: AsyncClient, session: AsyncSession, project, task: Task
):
    other = Task(project_id=project.id, title="Keep me", request="untouched")
    session.add(other)
    await session.commit()
    await session.refresh(other)

    await client.delete(f"/api/v1/tasks/{task.id}")

    survivor = await client.get(f"/api/v1/tasks/{other.id}")
    assert survivor.status_code == 200
    assert survivor.json()["title"] == "Keep me"


async def test_deleting_a_running_task_is_refused(
    client: AsyncClient, session: AsyncSession, task: Task
):
    """Deleting mid-run would leave the worker writing to rows that no longer
    exist."""
    await _running_run(session, task)

    response = await client.delete(f"/api/v1/tasks/{task.id}")

    assert response.status_code == 409
    assert "Cancel it first" in response.json()["detail"]
    assert (await client.get(f"/api/v1/tasks/{task.id}")).status_code == 200


async def test_deleting_an_unknown_task_is_404(client: AsyncClient):
    assert (await client.delete("/api/v1/tasks/9999")).status_code == 404


async def test_deleting_is_idempotent_from_the_callers_view(
    client: AsyncClient, task: Task
):
    assert (await client.delete(f"/api/v1/tasks/{task.id}")).status_code == 204
    assert (await client.delete(f"/api/v1/tasks/{task.id}")).status_code == 404


async def test_another_user_cannot_delete_your_task(
    client: AsyncClient, kv: InMemoryKVStore, other_users_task, app_mode
):
    _, bob, task = other_users_task
    await _sign_in(client, kv, bob)

    assert (await client.delete(f"/api/v1/tasks/{task.id}")).status_code == 404


async def test_the_owner_can_delete_their_own_task(
    client: AsyncClient, kv: InMemoryKVStore, other_users_task, app_mode
):
    alice, _, task = other_users_task
    await _sign_in(client, kv, alice)

    assert (await client.delete(f"/api/v1/tasks/{task.id}")).status_code == 204


async def test_deleting_leaves_the_project_intact(
    client: AsyncClient, session: AsyncSession, project, task: Task
):
    """Only the task goes — never the repository record it belonged to."""
    await client.delete(f"/api/v1/tasks/{task.id}")

    projects = (await client.get("/api/v1/projects")).json()
    assert [p["id"] for p in projects] == [project.id]
