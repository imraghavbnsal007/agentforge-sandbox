"""Repository analysis job: clone -> heuristic facts -> optional Claude enrichment."""

import asyncio
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AgentMode, AnalysisStatus
from app.core.exceptions import NotFoundError
from app.llm.types import AnalysisParseError, LLMProviderError
from app.models import (
    Project,
    ProjectAnalysis,
    RepoFileSummary,
    RepoImprovementSuggestion,
)
from app.services.archive_extractor import extract_archives
from app.services.git_client import GitClient
from app.services.github_config import validate_github_project
from app.services.repo_facts import RepoFacts, collect_repo_facts, read_text_safely
from app.services.repo_insights import (
    UNKNOWN,
    build_repo_map,
    detect_api_routes,
    detect_entry_points,
    detect_project_type,
    score_health,
)
from app.services.sql_analyzer import (
    analyze_sql,
    deterministic_findings,
    schema_summary,
    schema_to_json,
)

logger = logging.getLogger(__name__)

MAX_EXCERPT_FILES = 12
MAX_EXCERPT_CHARS = 3000

ENRICHMENT_WARNING_PREFIX = (
    "Repository facts were analyzed successfully, but AI enrichment "
)

ENRICH_PROMPT = """You are analyzing a software repository to build an engineering brief.

STRICT GROUNDING RULES:
- Base every statement ONLY on the facts, file list, and excerpts below.
- Never invent frameworks, architecture, files, tables, or behavior.
- If a field cannot be determined from the material, use exactly this string:
  "Unable to determine from repository."
- Every suggestion MUST cite at least one real file from the file list and
  describe something concrete and checkable in that file. A vague suggestion
  like "improve code quality" is worthless; "table X in file Y lacks Z" is right.

Repository facts (deterministically detected — trust these):
- Project type: {project_type}
- Languages: {languages}
- Frameworks: {frameworks}
- Package manager: {package_manager}
- Test command: {test_command}
- Build command: {build_command}
- Entry points: {entry_points}
- Files ({file_count}{truncated}):
{file_tree}

SQL schema (parsed from the .sql files; empty if not a SQL project):
{schema_summary}

Findings already detected deterministically (do not repeat these):
{findings}

README (may be empty):
{readme}

Key file excerpts:
{excerpts}

If this is a SQL project, compare the parsed schema against the README's
business rules and flag rules that have no enforcing constraint, citing the
table and file (e.g. a numeric limit with no CHECK, a domain with no CHECK or
lookup table, a derived value with no trigger/procedure).

Respond with ONLY a JSON object (no markdown fences) with exactly these keys:
- "summary": 2-4 sentences: what this project is and its purpose.
- "architecture_notes": 2-5 sentences on how the pieces are organized and interact.
- "risk_areas": array of 1-4 short strings, each one weak spot grounded in
  specific files/tables.
- "file_purposes": array of the 5-15 most important files, each
  {{"file_path": str, "purpose": one sentence, "importance_score": integer 0-100}}.
- "suggestions": array of 3-8 concrete improvements, each
  {{"title": short imperative phrase naming the file/table concerned,
    "description": 1-3 sentences describing exactly what is missing or wrong,
    "category": one of "testing"|"docs"|"structure"|"security"|"quality",
    "priority": "high"|"medium"|"low",
    "confidence": "high"|"medium"|"low" — how certain you are given the evidence,
    "estimated_effort": "small"|"medium"|"large",
    "reasoning": one or two sentences citing the evidence (file, statement, README rule),
    "related_files": non-empty array of paths from the file list}}.
Only reference paths that appear in the file list."""


def _facts_excerpts(root: Path, facts: RepoFacts) -> str:
    parts = []
    seen: set[str] = set()
    # SQL files and README first — they carry the most analyzable signal.
    sql_files = [f for f in facts.files if f.endswith(".sql")]
    candidates = (
        sql_files + [path for path, *_ in facts.important_files] + facts.files
    )
    for rel_path in candidates:
        if rel_path in seen or len(seen) >= MAX_EXCERPT_FILES:
            continue
        text = read_text_safely(root, rel_path)
        if text is None:
            continue
        seen.add(rel_path)
        parts.append(f"### {rel_path}\n```\n{text[:MAX_EXCERPT_CHARS]}\n```")
    return "\n\n".join(parts)


class ServiceAnalyst:
    """Builds the enrichment prompt and calls whichever provider the
    project's analysis phase resolves to, via LLMService."""

    def __init__(self, service, spec) -> None:
        self.service = service
        self.spec = spec

    async def enrich(
        self, root: Path, facts: RepoFacts, context: dict | None = None
    ) -> dict:
        context = context or {}
        prompt = ENRICH_PROMPT.format(
            project_type=context.get("project_type") or UNKNOWN,
            languages=", ".join(facts.languages) or "none detected",
            frameworks=", ".join(facts.frameworks) or "none detected",
            package_manager=facts.package_manager or "none detected",
            test_command=facts.test_command or "none detected",
            build_command=facts.build_command or "none detected",
            entry_points=", ".join(context.get("entry_points") or []) or "none detected",
            file_count=len(facts.files),
            truncated=", truncated" if facts.truncated else "",
            file_tree="\n".join(f"  {f}" for f in facts.files),
            schema_summary=context.get("schema_summary") or "(not a SQL project)",
            findings=context.get("findings") or "(none)",
            readme=facts.readme or "(no README)",
            excerpts=_facts_excerpts(root, facts) or "(none)",
        )
        return await self.service.analyze_repository(self.spec, prompt)


async def latest_completed_analysis(
    session: AsyncSession, project_id: int
) -> ProjectAnalysis | None:
    result = await session.execute(
        select(ProjectAnalysis)
        .where(
            ProjectAnalysis.project_id == project_id,
            ProjectAnalysis.status == AnalysisStatus.completed,
        )
        .order_by(ProjectAnalysis.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


class AnalysisService:
    def __init__(
        self,
        session: AsyncSession,
        git: GitClient | None = None,
        analyst: "ServiceAnalyst | None" = None,
    ) -> None:
        self.session = session
        self._git = git
        self._analyst = analyst

    async def run_analysis(self, analysis_id: int) -> ProjectAnalysis:
        from sqlalchemy.orm import selectinload

        # Eager-load the collections: the job session fetches this row fresh,
        # and a lazy load on first append would raise MissingGreenlet.
        result = await self.session.execute(
            select(ProjectAnalysis)
            .where(ProjectAnalysis.id == analysis_id)
            .options(
                selectinload(ProjectAnalysis.file_summaries),
                selectinload(ProjectAnalysis.suggestions),
            )
        )
        analysis = result.scalar_one_or_none()
        if analysis is None:
            raise NotFoundError(f"Analysis {analysis_id} not found")
        project = await self.session.get(Project, analysis.project_id)

        log_lines: list[str] = []

        def log(message: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            log_lines.append(f"[{stamp}] {message}")
            analysis.analysis_logs = "\n".join(log_lines)

        analysis.status = AnalysisStatus.running
        log(f"analysis started for {project.name}")
        await self.session.commit()

        clone_dir: Path | None = None
        try:
            validate_github_project(project)
            git = self._git or GitClient(token=settings.github_token)
            clone_dir = Path(tempfile.mkdtemp(prefix="agentforge-analysis-"))
            await git.clone(project.repo_url, clone_dir, project.default_branch)
            log(f"cloned {project.github_owner}/{project.github_repo}")

            extracted = await asyncio.to_thread(extract_archives, clone_dir)
            for archive_path, count in extracted:
                log(
                    f"extracted archive {archive_path} ({count} files) — "
                    "analysis only, never committed"
                )

            facts = await asyncio.to_thread(collect_repo_facts, clone_dir)
            log(
                f"heuristics: {len(facts.files)} files, "
                f"languages={facts.languages or ['unknown']}, "
                f"package_manager={facts.package_manager or 'none'}, "
                f"test_command={facts.test_command or 'none detected'}"
            )
            analysis.languages = facts.languages
            analysis.frameworks = facts.frameworks
            analysis.dependencies = facts.dependencies
            analysis.package_manager = facts.package_manager
            analysis.build_command = facts.build_command
            analysis.test_command = facts.test_command

            # SQL schema analysis (grounded, regex-parsed).
            sql_files = {}
            for rel in facts.files:
                if rel.endswith(".sql"):
                    text = read_text_safely(clone_dir, rel)
                    if text is not None:
                        sql_files[rel] = text
            schema = analyze_sql(sql_files)
            findings: list[dict] = []
            if schema is not None:
                analysis.sql_schema = schema_to_json(schema)
                analysis.schema_summary = schema_summary(schema)
                findings = deterministic_findings(schema)
                log(
                    f"SQL schema: {len(schema.tables)} tables, "
                    f"{len(schema.views)} views, {len(schema.procedures)} procedures, "
                    f"{len(schema.triggers)} triggers, {len(schema.indexes)} indexes"
                )

            # Deterministic insights.
            routes = await asyncio.to_thread(detect_api_routes, clone_dir, facts)
            analysis.api_routes = routes or None
            analysis.entry_points = detect_entry_points(facts) or None
            analysis.project_type = detect_project_type(facts, schema)
            analysis.repo_map = build_repo_map(facts, schema, routes)
            health = await asyncio.to_thread(score_health, facts, schema, clone_dir)
            analysis.health_score = health["overall"]
            analysis.health_breakdown = health["breakdown"]
            log(
                f"insights: type={analysis.project_type!r}, "
                f"{len(routes)} API routes, health score {health['overall']}/100"
            )

            for finding in findings:
                analysis.suggestions.append(
                    RepoImprovementSuggestion(
                        title=finding["title"][:300],
                        description=finding["description"],
                        category=finding["category"],
                        priority=finding["priority"],
                        confidence=finding["confidence"],
                        effort=finding["effort"],
                        reasoning=finding["reasoning"],
                        related_files=finding["related_files"],
                    )
                )
            if findings:
                log(f"{len(findings)} deterministic finding(s) recorded")

            for path, ftype, score, purpose in facts.important_files:
                analysis.file_summaries.append(
                    RepoFileSummary(
                        file_path=path,
                        file_type=ftype,
                        purpose=purpose,
                        importance_score=score,
                    )
                )
            await self.session.commit()

            analyst = self._analyst
            spec = None
            if analyst is None and settings.agent_mode == AgentMode.llm:
                from app.llm.base import get_provider_class
                from app.llm.profiles import resolve_specs
                from app.llm.service import LLMService

                spec = resolve_specs(
                    None, None, None,
                    project.preferred_provider,
                    project.preferred_model,
                    project.preferred_execution_profile,
                )["analysis"]
                if get_provider_class(spec.provider).is_configured():
                    analyst = ServiceAnalyst(
                        LLMService(
                            self.session,
                            project_id=project.id,
                            analysis_id=analysis.id,
                        ),
                        spec,
                    )
                else:
                    log(
                        f"AI enrichment skipped — provider {spec.provider!r} "
                        "has no credentials configured"
                    )
            if analyst is not None:
                log(
                    "AI enrichment via "
                    + (f"{spec.provider}/{spec.model}" if spec else "injected analyst")
                )
                context = {
                    "project_type": analysis.project_type,
                    "entry_points": analysis.entry_points,
                    "schema_summary": analysis.schema_summary,
                    "findings": "\n".join(f"- {f['title']}" for f in findings),
                }
                try:
                    data = await analyst.enrich(clone_dir, facts, context)
                except LLMProviderError as exc:
                    # Deterministic results are already computed and
                    # committed — enrichment failure must not sink them.
                    verb = (
                        "could not be parsed"
                        if isinstance(exc, AnalysisParseError)
                        else "failed"
                    )
                    analysis.enrichment_warning = (
                        f"{ENRICHMENT_WARNING_PREFIX}{verb}: {exc}"[:2000]
                    )
                    diagnostics = getattr(exc, "diagnostics", None)
                    if diagnostics is not None:
                        log(diagnostics.render())
                    log(
                        "AI enrichment failed — deterministic results "
                        "preserved. Use Re-analyze Repository to retry."
                    )
                    analysis.summary = analysis.summary or (
                        facts.readme.split("\n\n")[0][:500]
                        or f"{project.name}: no README found."
                    )
                else:
                    dropped = self._apply_enrichment(
                        analysis, data, set(facts.files),
                        {p: t for p, t, *_ in facts.important_files},
                    )
                    log(
                        f"enrichment done: {len(analysis.file_summaries)} file summaries, "
                        f"{len(analysis.suggestions)} suggestions"
                        + (f" ({dropped} ungrounded suggestion(s) dropped)" if dropped else "")
                    )
            else:
                analysis.summary = (
                    facts.readme.split("\n\n")[0][:500]
                    or f"{project.name}: no README found."
                )
                log("AI enrichment skipped (mock mode or no API credentials)")

            if not facts.test_command:
                log("no automated test command detected")
            analysis.status = AnalysisStatus.completed
            analysis.finished_at = datetime.now(timezone.utc)
            log("analysis complete")
            await self.session.commit()
        except Exception as exc:
            logger.exception("Analysis %s failed", analysis_id)
            # A flush error leaves the session unusable until rolled back.
            await self.session.rollback()
            log(f"analysis failed: {exc}")
            analysis.status = AnalysisStatus.failed
            analysis.error = str(exc)
            analysis.finished_at = datetime.now(timezone.utc)
            await self.session.commit()
        finally:
            if clone_dir is not None:
                shutil.rmtree(clone_dir, ignore_errors=True)
        return analysis

    def _apply_enrichment(
        self,
        analysis: ProjectAnalysis,
        data: dict,
        known_files: set[str],
        file_types: dict[str, str] | None = None,
    ) -> int:
        """Apply schema-validated enrichment; returns dropped-suggestion count.

        `data` is an EnrichmentResult dump — types and enum values are
        already normalized. Grounding (paths must exist in the repo) is
        still enforced here because the schema cannot know the file list.
        """
        file_types = file_types or {}
        analysis.summary = str(data.get("summary") or "")[:2000] or analysis.summary
        analysis.architecture_notes = str(data.get("architecture_notes") or "")[:4000]
        analysis.risk_areas = "\n".join(
            str(r) for r in (data.get("risk_areas") or [])
        )[:4000]

        enriched = {}
        for item in data.get("file_purposes") or []:
            path = item["file_path"]
            if path in known_files:
                enriched[path] = item
        if enriched:
            analysis.file_summaries.clear()
            for path, item in enriched.items():
                analysis.file_summaries.append(
                    RepoFileSummary(
                        file_path=path,
                        file_type=file_types.get(path, "")[:50],
                        purpose=str(item.get("purpose") or "")[:1000],
                        importance_score=item.get("importance_score", 50),
                    )
                )

        dropped = 0
        existing_titles = {s.title.lower() for s in analysis.suggestions}
        for item in data.get("suggestions") or []:
            if not item.get("title"):
                dropped += 1
                continue
            related = [
                str(f) for f in (item.get("related_files") or []) if str(f) in known_files
            ]
            if not related:
                # Suggestions must reference actual files — ungrounded ones go.
                dropped += 1
                continue
            title = str(item["title"])[:300]
            if title.lower() in existing_titles:
                continue  # deterministic finding already covers it
            analysis.suggestions.append(
                RepoImprovementSuggestion(
                    title=title,
                    description=str(item.get("description") or "")[:2000],
                    category=item.get("category", "quality"),
                    priority=item.get("priority", "medium"),
                    confidence=item.get("confidence", "medium"),
                    effort=item.get("estimated_effort", "medium"),
                    reasoning=str(item.get("reasoning") or "")[:2000],
                    related_files=related,
                )
            )
        return dropped
