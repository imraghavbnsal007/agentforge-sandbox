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


async def test_github_project_goes_ready_for_review(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import Project
    from tests.helpers import local_user_id

    project = Project(
        user_id=await local_user_id(session),
        name="GH",
        repo_url="https://github.com/acme/widget.git",
        github_owner="acme",
        github_repo="widget",
    )
    session.add(project)
    await session.flush()
    task = Task(project_id=project.id, title="T", request="R")
    session.add(task)
    await session.commit()

    from app.core.config import settings

    async def fake_factory(_project):
        return Workspace.create_from(settings.sample_repo_path)

    # Tests green -> ready_for_review, run completed.
    service = RunService(
        session,
        runner=MockRunner(delay=0),
        executor=FakeExecutor(),
        workspace_factory=fake_factory,
    )
    run = await service.execute_agent_run(task.id)
    assert run.status == RunStatus.completed
    assert task.status == TaskStatus.ready_for_review
    assert "ready for review" in run.log

    # Tests red -> completed, no review gate.
    task2 = Task(project_id=project.id, title="T2", request="R")
    session.add(task2)
    await session.commit()
    service = RunService(
        session,
        runner=MockRunner(delay=0),
        executor=FakeExecutor(passed=1, failed=3),
        workspace_factory=fake_factory,
    )
    await service.execute_agent_run(task2.id)
    assert task2.status == TaskStatus.completed


async def test_analyzed_project_uses_detected_test_command_and_no_tests_path(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    from app.core.config import settings
    from app.core.enums import AnalysisStatus
    from app.models import Project, ProjectAnalysis
    from tests.helpers import local_user_id

    project = Project(
        user_id=await local_user_id(session),
        name="GH2",
        repo_url="https://github.com/acme/w2.git",
        github_owner="acme",
        github_repo="w2",
    )
    session.add(project)
    await session.flush()
    # Completed analysis that detected NO test command.
    session.add(
        ProjectAnalysis(
            project_id=project.id,
            status=AnalysisStatus.completed,
            test_command=None,
            finished_at=datetime.now(timezone.utc),
            file_summaries=[],
            suggestions=[],
        )
    )
    task = Task(project_id=project.id, title="T", request="R")
    session.add(task)
    await session.commit()

    async def fake_factory(_project):
        return Workspace.create_from(settings.sample_repo_path)

    service = RunService(
        session, runner=MockRunner(delay=0), workspace_factory=fake_factory
    )
    run = await service.execute_agent_run(task.id)

    # Honest no-tests path: ready for review, no fabricated results.
    assert task.status == TaskStatus.ready_for_review
    assert run.test_results == []
    assert "No automated test command detected" in run.log
    assert "WITHOUT test verification" in run.log

    # Now with a detected command: it is actually executed.
    # (sys.executable because the bare `python` of the container isn't
    # guaranteed on dev machines.)
    import sys

    detected = f"{sys.executable} -m pytest -q"
    session.add(
        ProjectAnalysis(
            project_id=project.id,
            status=AnalysisStatus.completed,
            test_command=detected,
            finished_at=datetime.now(timezone.utc),
            file_summaries=[],
            suggestions=[],
        )
    )
    task2 = Task(project_id=project.id, title="T2", request="R")
    session.add(task2)
    await session.commit()
    run2 = await RunService(
        session, runner=MockRunner(delay=0), workspace_factory=fake_factory
    ).execute_agent_run(task2.id)
    assert task2.status == TaskStatus.ready_for_review
    assert run2.test_results[0].suite == detected
    assert run2.test_results[0].passed == 7


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
