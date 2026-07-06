from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import AgentMode, ChangeType, RunStatus


class FileChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    change_type: ChangeType
    diff: str


class TestResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    suite: str
    passed: int
    failed: int
    errored: int
    duration: float
    output: str


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    mode: AgentMode
    status: RunStatus
    plan: list[str] | None
    summary: str | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    file_changes: list[FileChangeRead]
    test_results: list[TestResultRead]
