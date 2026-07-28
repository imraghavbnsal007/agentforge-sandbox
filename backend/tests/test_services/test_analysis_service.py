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
    def __init__(self) -> None:
        self.context: dict | None = None

    async def enrich(self, root: Path, facts, context: dict | None = None) -> dict:
        from app.llm.analysis_schema import validate_enrichment

        self.context = context
        raw = {
            "summary": "A tiny calculator project.",
            "architecture_notes": "Flat module layout.",
            "risk_areas": "string_utils has no edge-case tests.",
            "file_purposes": [
                {"file_path": "calculator.py",
                 "purpose": "Arithmetic functions", "importance_score": 95},
                {"file_path": "hallucinated.py",
                 "purpose": "does not exist", "importance_score": 99},
            ],
            "suggestions": [
                {"title": "Add edge-case tests", "description": "Cover zero and negatives.",
                 "category": "testing", "priority": "high", "confidence": "high",
                 "estimated_effort": "small",
                 "reasoning": "test_calculator.py only covers happy paths.",
                 "related_files": ["tests/test_calculator.py", "fake.py"]},
                {"title": "Weird fields get normalized", "description": "x",
                 "category": "nonsense", "priority": "urgent", "confidence": "certain",
                 "estimated_effort": "huge", "related_files": ["calculator.py"]},
                {"title": "Ungrounded suggestion", "description": "no files cited",
                 "category": "quality", "priority": "low", "related_files": []},
                {"title": "Hallucinated files only", "description": "cites nothing real",
                 "category": "quality", "priority": "low",
                 "related_files": ["does_not_exist.py"]},
            ],
        }
        # Mirror the real contract: the provider layer returns a
        # schema-validated dump, never a raw model response.
        return validate_enrichment(raw).model_dump()


class ParseFailingAnalyst:
    """Simulates the provider raising AnalysisParseError with diagnostics."""

    async def enrich(self, root: Path, facts, context: dict | None = None) -> dict:
        from app.llm.json_extract import JSONExtractionError, ParseDiagnostics
        from app.llm.types import AnalysisParseError

        exc = JSONExtractionError("balanced_scan", "no parseable JSON")
        raise AnalysisParseError(
            "Google Gemini returned unparseable analysis JSON",
            diagnostics=ParseDiagnostics.from_failure(
                provider="google",
                model="gemini-3.5-flash",
                response_text="I could not produce JSON, sorry",
                exc=exc,
                mime_type="application/json",
                finish_reason="MAX_TOKENS",
            ),
        )


async def _make_analysis(session: AsyncSession) -> int:
    from tests.helpers import local_user_id

    project = Project(
        user_id=await local_user_id(session),
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
    # Invalid category/priority/confidence/effort are normalized.
    suggestion = next(s for s in result.suggestions if "normalized" in s.title)
    assert suggestion.category == "quality" and suggestion.priority == "medium"
    assert suggestion.confidence == "medium" and suggestion.effort == "medium"
    good = next(s for s in result.suggestions if s.title == "Add edge-case tests")
    assert good.related_files == ["tests/test_calculator.py"]
    assert good.confidence == "high" and good.effort == "small"
    assert "happy paths" in good.reasoning
    # Suggestions without a single real file are dropped entirely.
    titles = [s.title for s in result.suggestions]
    assert "Ungrounded suggestion" not in titles
    assert "Hallucinated files only" not in titles
    # Deterministic insights are stored.
    assert result.project_type == "Python project"
    assert result.health_score is not None
    assert set(result.health_breakdown) == {
        "structure", "documentation", "testing", "maintainability", "security",
    }
    assert result.repo_map
    assert "analysis complete" in result.analysis_logs

    found = await latest_completed_analysis(session, result.project_id)
    assert found is not None and found.id == analysis_id


async def test_enrichment_parse_failure_degrades_gracefully(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """A parse failure must not sink the deterministic analysis."""
    monkeypatch.setattr(settings, "github_token", "tok")
    analysis_id = await _make_analysis(session)
    service = AnalysisService(
        session,
        git=FakeGit(Path(settings.sample_repo_path)),
        analyst=ParseFailingAnalyst(),
    )
    result = await service.run_analysis(analysis_id)

    # The analysis completes with a warning instead of failing.
    assert result.status == AnalysisStatus.completed
    assert result.error is None
    assert result.enrichment_warning is not None
    assert "could not be parsed" in result.enrichment_warning
    # Deterministic facts are all preserved.
    assert result.languages == ["Python"]
    assert result.test_command == "python -m pytest -q"
    assert result.project_type == "Python project"
    assert result.health_score is not None
    assert result.repo_map
    assert result.summary  # README fallback
    # Sanitized diagnostics land in the logs — with the finish reason.
    assert "enrichment parse diagnostics" in result.analysis_logs
    assert "finish_reason=MAX_TOKENS" in result.analysis_logs
    assert "failed_stage=balanced_scan" in result.analysis_logs
    assert "Re-analyze Repository" in result.analysis_logs
    # It still counts as a completed analysis.
    found = await latest_completed_analysis(session, result.project_id)
    assert found is not None and found.id == analysis_id


async def test_successful_enrichment_leaves_no_warning(
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
    assert result.enrichment_warning is None


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


async def test_analysis_of_archived_sql_project(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A repo whose SQL lives inside a ZIP is analyzed like normal files."""
    import zipfile

    monkeypatch.setattr(settings, "github_token", "tok")
    monkeypatch.setattr(settings, "agent_mode", "mock")
    fixture = tmp_path / "repo"
    fixture.mkdir()
    (fixture / "README.md").write_text("# Restaurant DB\nBookings max 6 people.")
    with zipfile.ZipFile(fixture / "DataBase Project.zip", "w") as zf:
        zf.writestr(
            "Project_ddl.sql",
            "CREATE TABLE booking (bookingid NUMBER(7) NOT NULL, custid NUMBER(7));\n"
            "ALTER TABLE booking ADD CONSTRAINT booking_pk PRIMARY KEY (bookingid);\n"
            "DROP VIEW booking_receipt;\n",
        )

    analysis_id = await _make_analysis(session)
    result = await AnalysisService(session, git=FakeGit(fixture)).run_analysis(
        analysis_id
    )

    assert result.status == AnalysisStatus.completed
    assert "extracted archive DataBase Project.zip" in result.analysis_logs
    assert result.sql_schema is not None
    assert result.sql_schema["tables"][0]["name"] == "booking"
    assert result.sql_schema["tables"][0]["primary_key"] == ["bookingid"]
    assert result.project_type == "SQL database schema project"
    assert "booking" in result.schema_summary
    # Deterministic findings reference the extracted file path.
    finding_files = [
        f for s in result.suggestions for f in (s.related_files or [])
    ]
    assert any(".extracted/" in f and f.endswith("Project_ddl.sql") for f in finding_files)
    titles = [s.title for s in result.suggestions]
    assert any("booking_receipt" in t for t in titles)
    assert any("custid" in t for t in titles)


async def test_analysis_missing_token_fails_clearly(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_token", "")
    analysis_id = await _make_analysis(session)
    result = await AnalysisService(session).run_analysis(analysis_id)
    assert result.status == AnalysisStatus.failed
    assert "GITHUB_TOKEN" in result.error
