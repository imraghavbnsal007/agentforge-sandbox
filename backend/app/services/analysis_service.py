"""Repository analysis job: clone -> heuristic facts -> optional Claude enrichment."""

import asyncio
import json
import logging
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import AgentMode, AnalysisStatus
from app.core.exceptions import NotFoundError
from app.models import (
    Project,
    ProjectAnalysis,
    RepoFileSummary,
    RepoImprovementSuggestion,
)
from app.services.git_client import GitClient
from app.services.github_config import validate_github_project
from app.services.repo_facts import RepoFacts, collect_repo_facts, read_text_safely

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"testing", "docs", "structure", "security", "quality"}
VALID_PRIORITIES = {"high", "medium", "low"}
MAX_EXCERPT_FILES = 12
MAX_EXCERPT_CHARS = 3000

ENRICH_PROMPT = """You are analyzing a software repository to build an engineering brief.

Repository facts (heuristically detected):
- Languages: {languages}
- Frameworks: {frameworks}
- Package manager: {package_manager}
- Test command: {test_command}
- Build command: {build_command}
- Files ({file_count}{truncated}):
{file_tree}

README (may be empty):
{readme}

Key file excerpts:
{excerpts}

Respond with ONLY a JSON object (no markdown fences) with exactly these keys:
- "summary": 2-4 sentences: what this project is and its purpose.
- "architecture_notes": 2-5 sentences on how the code is organized and flows.
- "risk_areas": 1-4 sentences on missing tests, weak spots, or fragile areas.
- "files": array of the 5-15 most important files, each
  {{"path": str, "file_type": one of "entrypoint"|"config"|"core"|"docs"|"tests"|"infra"|"ci",
    "purpose": one sentence, "importance": integer 0-100}}.
- "suggestions": array of 3-6 concrete improvements, each
  {{"title": short imperative phrase, "description": 1-3 sentences,
    "category": one of "testing"|"docs"|"structure"|"security"|"quality",
    "priority": "high"|"medium"|"low", "related_files": array of paths}}.
Only reference paths that appear in the file list."""


def _facts_excerpts(root: Path, facts: RepoFacts) -> str:
    parts = []
    seen: set[str] = set()
    candidates = [path for path, *_ in facts.important_files] + facts.files
    for rel_path in candidates:
        if rel_path in seen or len(seen) >= MAX_EXCERPT_FILES:
            continue
        text = read_text_safely(root, rel_path)
        if text is None:
            continue
        seen.add(rel_path)
        parts.append(f"### {rel_path}\n```\n{text[:MAX_EXCERPT_CHARS]}\n```")
    return "\n\n".join(parts)


class ClaudeRepoAnalyst:
    """One Claude call that turns collected facts into the semantic fields."""

    def __init__(self, client=None, model: str | None = None) -> None:
        import anthropic

        if client is None:
            client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key or None
            )
            if not client.api_key and not client.auth_token:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set — required for AI analysis "
                    "in llm mode"
                )
        self.client = client
        self.model = model or settings.anthropic_model

    async def enrich(self, root: Path, facts: RepoFacts) -> dict:
        import anthropic

        prompt = ENRICH_PROMPT.format(
            languages=", ".join(facts.languages) or "unknown",
            frameworks=", ".join(facts.frameworks) or "none detected",
            package_manager=facts.package_manager or "none detected",
            test_command=facts.test_command or "none detected",
            build_command=facts.build_command or "none detected",
            file_count=len(facts.files),
            truncated=", truncated" if facts.truncated else "",
            file_tree="\n".join(f"  {f}" for f in facts.files),
            readme=facts.readme or "(no README)",
            excerpts=_facts_excerpts(root, facts) or "(none)",
        )
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIStatusError as exc:
            raise RuntimeError(
                f"Claude API error during analysis ({exc.status_code}): {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(
                "Could not reach the Claude API during analysis"
            ) from exc
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Claude returned unparseable analysis JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Claude analysis JSON was not an object")
        return data


def _enricher_available() -> bool:
    import os

    return settings.agent_mode == AgentMode.llm and bool(
        settings.anthropic_api_key
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )


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
        analyst: ClaudeRepoAnalyst | None = None,
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
            if analyst is None and _enricher_available():
                analyst = ClaudeRepoAnalyst()
            if analyst is not None:
                log(f"AI enrichment via {settings.anthropic_model}")
                data = await analyst.enrich(clone_dir, facts)
                self._apply_enrichment(analysis, data, set(facts.files))
                log(
                    f"enrichment done: {len(analysis.file_summaries)} file summaries, "
                    f"{len(analysis.suggestions)} suggestions"
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
        self, analysis: ProjectAnalysis, data: dict, known_files: set[str]
    ) -> None:
        analysis.summary = str(data.get("summary") or "")[:2000] or analysis.summary
        analysis.architecture_notes = str(data.get("architecture_notes") or "")[:4000]
        analysis.risk_areas = str(data.get("risk_areas") or "")[:4000]

        enriched = {}
        for item in data.get("files") or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if path not in known_files:
                continue
            enriched[path] = item
        if enriched:
            analysis.file_summaries.clear()
            for path, item in enriched.items():
                analysis.file_summaries.append(
                    RepoFileSummary(
                        file_path=path,
                        file_type=str(item.get("file_type") or "")[:50],
                        purpose=str(item.get("purpose") or "")[:1000],
                        importance_score=max(0, min(100, int(item.get("importance") or 0))),
                    )
                )

        for item in data.get("suggestions") or []:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            category = str(item.get("category") or "quality").lower()
            priority = str(item.get("priority") or "medium").lower()
            related = [
                str(f) for f in (item.get("related_files") or []) if str(f) in known_files
            ]
            analysis.suggestions.append(
                RepoImprovementSuggestion(
                    title=str(item["title"])[:300],
                    description=str(item.get("description") or "")[:2000],
                    category=category if category in VALID_CATEGORIES else "quality",
                    priority=priority if priority in VALID_PRIORITIES else "medium",
                    related_files=related,
                )
            )
