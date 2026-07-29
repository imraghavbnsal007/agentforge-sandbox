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


# -- failing mid-generation -------------------------------------------------
#
# The regression these guard: `session.rollback()` in the failure handler
# expires every ORM instance, and the handler then *read* `run.progress`.
# In an async session that lazy-load raises MissingGreenlet, so the real
# error never reached the database and the run stayed `running` until the
# reaper mislabelled it "the worker stopped". See runs 16 and 17 (2026-07-29).


class DirtyExplodingRunner(MockRunner):
    """Fails the way the real LLM runner does — with work pending.

    `ExplodingRunner` raises on a clean session, where rollback() is a no-op
    and nothing is expired. The LLM service writes an `llm_runs` row per API
    call, so by the time generation fails there is a live transaction for the
    rollback to actually roll back. That is what expires the instances.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(delay=0)
        self._session = session

    async def apply_changes(self, title, request, plan, workspace, log):
        from app.models import LLMRun

        self._session.add(
            LLMRun(provider="google", model="gemini-3.1-flash-lite", phase="coding")
        )
        await self._session.flush()
        raise RuntimeError("Edit loop exceeded 20 iterations")


async def test_a_failure_mid_generation_records_the_real_error(
    session: AsyncSession, task: Task
) -> None:
    service = RunService(
        session, runner=DirtyExplodingRunner(session), executor=FakeExecutor()
    )
    run = await service.execute_agent_run(task.id)

    assert run.status == RunStatus.failed
    assert run.finished_at is not None
    # The actual cause, not a guess made five minutes later by the reaper.
    assert "Edit loop exceeded 20 iterations" in (run.error or "")
    assert task.status == TaskStatus.failed


async def test_a_failure_mid_generation_keeps_the_log(
    session: AsyncSession, task: Task
) -> None:
    """The log is rebuilt from memory after the rollback, not lost with it."""
    service = RunService(
        session, runner=DirtyExplodingRunner(session), executor=FakeExecutor()
    )
    run = await service.execute_agent_run(task.id)

    assert run.log is not None
    assert "agent run started" in run.log
    assert "run failed: Edit loop exceeded 20 iterations" in run.log
