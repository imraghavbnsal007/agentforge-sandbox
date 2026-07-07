from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AgentMode, TaskStatus
from app.schemas.run import AgentRunRead


class TaskCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=200)
    request: str = Field(min_length=1)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    request: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    # Mode of the most recent run, populated on list/detail reads.
    latest_run_mode: AgentMode | None = None


class TaskDetail(TaskRead):
    latest_run: AgentRunRead | None = None
    # Full run history (oldest first) for the raw-logs debugging view.
    runs: list[AgentRunRead] = []
