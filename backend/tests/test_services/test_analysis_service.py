import shutil
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AnalysisStatus
from app.models import Project, ProjectAnalysis
from app.services.analysis_service import AnalysisService, latest_completed_analysis
from app.services.git_client import GitError


class FakeGit:
    """'Clones' by copying a local fixture directory."""

    def __init__(self, source: Path) -> None:
        self.source = source

    async def clone(self, repo_url: str, dest: Path, branch: str) -> None:
        shutil.copytree(self.source, dest, dirs_exist_ok=True)


class FailingGit:
    async def clone(self, repo_url: str, dest: Path, branch: str) -> None:
        raise GitError("git clone failed: repository not found")


class FakeAnalyst:
    async def enrich(self, root: Path, facts) -> dict:
        return {
            "summary": "A tiny calculator project.",
            "architecture_notes": "Flat module layout.",
            "risk_areas": "string_utils has no edge-case tests.",
            "files": [
                {"path": "calculator.py", "file_type": "core",
                 "purpose": "Arithmetic functions", "importance": 95},
                {"path": "hallucinated.py", "file_type": "core",
                 "purpose": "does not exist", "importance": 99},
            ],
            "suggestions": [
                {"title": "Add edge-case tests", "description": "Cover zero and negatives.",
                 "category": "testing", "priority": "high",
                 "related_files": ["tests/test_calculator.py", "fake.py"]},
                {"title": "Weird category", "description": "x",
                 "category": "nonsense", "priority": "urgent", "related_files": []},
            ],
        }


async def _make_analysis(session: AsyncSession) -> int:
    project = Project(
        name="acme/widget",
        repo_path="",
        repo_url="https://github.com/acme/widget.git",
        default_branch="main",
        github_owner="acme",
        github_repo="widget",
    )
    session.add(project)
    await session.flush()
    analysis = ProjectAnalysis(project_id=project.id, file_summaries=[], suggestions=[])
    session.add(analysis)
    await session.commit()
    analysis_id = analysis.id
    # Simulate the worker: a fresh session has no relationship collections
    # loaded — this is what exposed the MissingGreenlet lazy-load bug.
    session.expire_all()
    return analysis_id


async def test_analysis_happy_path(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_token", "tok")
    analysis_id = await _make_analysis(session)
    service = AnalysisService(
        session,
        git=FakeGit(Path(settings.sample_repo_path)),
        analyst=FakeAnalyst(),
    )
    result = await service.run_analysis(analysis_id)

    assert result.status == AnalysisStatus.completed
    assert result.finished_at is not None
    assert result.languages == ["Python"]
    assert result.test_command == "python -m pytest -q"
    assert result.summary == "A tiny calculator project."
    assert result.risk_areas.startswith("string_utils")
    # Hallucinated paths are dropped.
    paths = [f.file_path for f in result.file_summaries]
    assert "calculator.py" in paths and "hallucinated.py" not in paths
    # Invalid category/priority are normalized.
    suggestion = next(s for s in result.suggestions if s.title == "Weird category")
    assert suggestion.category == "quality" and suggestion.priority == "medium"
    good = next(s for s in result.suggestions if s.title == "Add edge-case tests")
    assert good.related_files == ["tests/test_calculator.py"]
    assert "analysis complete" in result.analysis_logs

    found = await latest_completed_analysis(session, result.project_id)
    assert found is not None and found.id == analysis_id


async def test_analysis_without_analyst_uses_heuristics(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_token", "tok")
    monkeypatch.setattr(settings, "agent_mode", "mock")
    analysis_id = await _make_analysis(session)
    service = AnalysisService(session, git=FakeGit(Path(settings.sample_repo_path)))
    result = await service.run_analysis(analysis_id)

    assert result.status == AnalysisStatus.completed
    assert result.test_command == "python -m pytest -q"
    assert "enrichment skipped" in result.analysis_logs
    assert result.summary  # falls back to README/heuristic text


async def test_analysis_clone_failure(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_token", "tok")
    analysis_id = await _make_analysis(session)
    service = AnalysisService(session, git=FailingGit())
    result = await service.run_analysis(analysis_id)

    assert result.status == AnalysisStatus.failed
    assert "repository not found" in result.error
    assert "analysis failed" in result.analysis_logs
    assert await latest_completed_analysis(session, result.project_id) is None


async def test_analysis_missing_token_fails_clearly(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_token", "")
    analysis_id = await _make_analysis(session)
    result = await AnalysisService(session).run_analysis(analysis_id)
    assert result.status == AnalysisStatus.failed
    assert "GITHUB_TOKEN" in result.error
