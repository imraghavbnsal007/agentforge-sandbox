from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import AnalysisStatus


class FileSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_path: str
    file_type: str
    purpose: str
    importance_score: int


class SuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    category: str
    priority: str
    related_files: list[str] | None
    confidence: str
    reasoning: str
    effort: str


class AnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    status: AnalysisStatus
    summary: str | None
    languages: list[str] | None
    frameworks: list[str] | None
    dependencies: list[str] | None
    package_manager: str | None
    build_command: str | None
    test_command: str | None
    architecture_notes: str | None
    risk_areas: str | None
    project_type: str | None
    entry_points: list[str] | None
    api_routes: list[dict] | None
    repo_map: list[dict] | None
    sql_schema: dict | None
    schema_summary: str | None
    health_score: int | None
    health_breakdown: dict | None
    analysis_logs: str | None
    error: str | None
    enrichment_warning: str | None = None
    started_at: datetime
    finished_at: datetime | None
    file_summaries: list[FileSummaryRead]
    suggestions: list[SuggestionRead]
