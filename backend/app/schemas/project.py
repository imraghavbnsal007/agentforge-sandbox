from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AnalysisStatus
from app.schemas.analysis import AnalysisRead


class ProjectRegister(BaseModel):
    repo_url: str = Field(min_length=1, max_length=500)
    default_branch: str = Field(default="main", min_length=1, max_length=100)


class ProjectSettingsUpdate(BaseModel):
    preferred_provider: str | None = Field(default=None, max_length=30)
    preferred_model: str | None = Field(default=None, max_length=100)
    preferred_execution_profile: str | None = Field(default=None, max_length=20)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    repo_path: str = "sample_repo"
    # GitHub configuration; omit all of these for sample-repo mode.
    repo_url: str | None = None
    default_branch: str = "main"
    github_owner: str | None = None
    github_repo: str | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    repo_path: str
    repo_url: str | None
    default_branch: str
    github_owner: str | None
    github_repo: str | None
    preferred_provider: str | None
    preferred_model: str | None
    preferred_execution_profile: str | None
    created_at: datetime
    # Latest-analysis snapshot, populated on reads.
    analysis_status: AnalysisStatus | None = None
    last_analyzed_at: datetime | None = None
    primary_language: str | None = None
    framework: str | None = None
    test_command: str | None = None


class ProjectDetail(ProjectRead):
    latest_analysis: AnalysisRead | None = None
