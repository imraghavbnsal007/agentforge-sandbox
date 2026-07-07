from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: datetime
