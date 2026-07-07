import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.executor import TestResultData
from app.agent.mock_runner import MockRunner
from app.agent.workspace import Workspace
from app.core.enums import ChangeType, RunStatus, TaskStatus
from app.core.exceptions import NotFoundError
from app.models import Task
from app.services.run_service import RunService


class FakeExecutor:
    """Skips the real pytest subprocess for fast unit tests."""

    def __init__(self, passed: int = 7, failed: int = 0) -> None:
        self.passed = passed
        self.failed = failed

    async def run_tests(self, workspace: Workspace) -> TestResultData:
        return TestResultData(
            suite="pytest",
            passed=self.passed,
            failed=self.failed,
            errored=0,
            duration=0.1,
            output=f"{self.passed} passed",
            stderr="",
        )


class ExplodingRunner(MockRunner):
    async def apply_changes(self, title, request, plan, workspace, log):
        raise RuntimeError("boom")


async def test_execute_agent_run_happy_path(session: AsyncSession, task: Task) -> None:
    service = RunService(session, runner=MockRunner(delay=0), executor=FakeExecutor())
    run = await service.execute_agent_run(task.id)

    assert run.status == RunStatus.completed
    assert task.status == TaskStatus.completed
    assert run.plan and len(run.plan) == 4
    changed = {c.path: c for c in run.file_changes}
    assert changed["calculator.py"].change_type == ChangeType.modify
    assert "+def multiply" in changed["calculator.py"].diff
    assert changed["tests/test_multiply.py"].change_type == ChangeType.create
    assert run.test_results[0].passed == 7
    assert run.summary is not None
    assert run.log and "run complete" in run.log
    assert run.finished_at is not None
    assert run.error is None


async def test_execute_agent_run_with_real_pytest(
    session: AsyncSession, task: Task
) -> None:
    """Integration: the mock runner's edit passes a real pytest run."""
    service = RunService(session, runner=MockRunner(delay=0))
    run = await service.execute_agent_run(task.id)

    assert run.status == RunStatus.completed
    result = run.test_results[0]
    # 5 sample repo tests + 2 added by the mock runner
    assert result.passed == 7
    assert result.failed == 0
    assert "passed" in result.output


async def test_execute_agent_run_missing_task(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await RunService(session).execute_agent_run(999)


async def test_execute_agent_run_failure_marks_task_failed(
    session: AsyncSession, task: Task
) -> None:
    service = RunService(
        session, runner=ExplodingRunner(delay=0), executor=FakeExecutor()
    )
    run = await service.execute_agent_run(task.id)

    assert run.status == RunStatus.failed
    assert run.error == "boom"
    assert run.log and "run failed: boom" in run.log
    assert task.status == TaskStatus.failed


async def test_llm_mode_without_api_key_fails_cleanly(
    session: AsyncSession, task: Task, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings
    from app.core.enums import AgentMode

    monkeypatch.setattr(settings, "agent_mode", AgentMode.llm)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    run = await RunService(session).execute_agent_run(task.id)

    assert run.status == RunStatus.failed
    assert "ANTHROPIC_API_KEY" in (run.error or "")
    assert task.status == TaskStatus.failed
