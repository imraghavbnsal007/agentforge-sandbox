from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AgentMode, TaskStatus
from app.schemas.run import AgentRunRead


class TaskCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=200)
    request: str = Field(min_length=1)
    # Optional LLM overrides; omitted -> project preferences -> defaults.
    llm_provider: str | None = Field(default=None, max_length=30)
    llm_model: str | None = Field(default=None, max_length=100)
    execution_profile: str | None = Field(default=None, max_length=20)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    request: str
    status: TaskStatus
    llm_provider: str | None
    llm_model: str | None
    execution_profile: str | None
    created_at: datetime
    updated_at: datetime
    # Populated from the most recent run on list/detail reads.
    latest_run_mode: AgentMode | None = None
    latest_run_pr_url: str | None = None


class TaskDetail(TaskRead):
    latest_run: AgentRunRead | None = None
    # Full run history (oldest first) for the raw-logs debugging view.
    runs: list[AgentRunRead] = []


class TaskEventRead(BaseModel):
    """One recorded event. `id` doubles as the replay cursor."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    run_id: int | None = None
    sequence_number: int
    event_type: str
    stage: str | None = None
    message: str | None = None
    progress: int | None = None
    error_code: str | None = None
    safe_metadata: dict | None = None
    created_at: datetime


class TaskEventPage(BaseModel):
    events: list[TaskEventRead] = []
    #: Pass back as `after_id` to continue; None when caught up.
    next_cursor: int | None = None
