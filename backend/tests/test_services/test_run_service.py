import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.stub_runner import StubAgentRunner
from app.core.enums import RunStatus, TaskStatus
from app.core.exceptions import NotFoundError
from app.models import Task
from app.services.run_service import RunService


class ExplodingRunner(StubAgentRunner):
    async def apply_changes(self, title: str, request: str):
        raise RuntimeError("boom")


async def test_execute_agent_run_happy_path(session: AsyncSession, task: Task) -> None:
    service = RunService(session, runner=StubAgentRunner(delay=0))
    run = await service.execute_agent_run(task.id)

    assert run.status == RunStatus.completed
    assert task.status == TaskStatus.completed
    assert run.plan is not None and len(run.plan) == 5
    assert len(run.file_changes) == 1
    assert run.file_changes[0].diff.startswith("---")
    assert len(run.test_results) == 1
    assert run.test_results[0].passed == 12
    assert run.summary is not None
    assert run.finished_at is not None
    assert run.error is None


async def test_execute_agent_run_missing_task(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await RunService(session).execute_agent_run(999)


async def test_execute_agent_run_failure_marks_task_failed(
    session: AsyncSession, task: Task
) -> None:
    service = RunService(session, runner=ExplodingRunner(delay=0))
    run = await service.execute_agent_run(task.id)

    assert run.status == RunStatus.failed
    assert run.error == "boom"
    assert run.finished_at is not None
    assert task.status == TaskStatus.failed


async def test_llm_mode_not_implemented_marks_task_failed(
    session: AsyncSession, task: Task, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings
    from app.core.enums import AgentMode

    monkeypatch.setattr(settings, "agent_mode", AgentMode.llm)
    run = await RunService(session).execute_agent_run(task.id)

    assert run.status == RunStatus.failed
    assert "Phase 2" in (run.error or "")
    assert task.status == TaskStatus.failed
