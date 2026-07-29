from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import AgentMode, ChangeType, RunStatus


class FileChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    path: str
    change_type: ChangeType
    diff: str
    is_binary: bool
    size_bytes: int | None
    content_hash: str | None


class TestResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    suite: str
    passed: int
    failed: int
    errored: int
    duration: float
    output: str
    stderr: str


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    mode: AgentMode
    status: RunStatus
    plan: list[str] | None
    summary: str | None
    log: str | None
    error: str | None
    #: Set when the agent stopped early. The run still succeeded — this warns
    #: that its changes may not be the whole job.
    incomplete_reason: str | None = None
    branch_name: str | None
    commit_sha: str | None
    pr_url: str | None
    # Actual provider/model this run used, from its llm_runs rows (not the
    # global default) — populated by the tasks route, absent for mock runs.
    llm_provider: str | None = None
    llm_model: str | None = None
    stage: str | None = None
    progress: int = 0
    error_code: str | None = None
    #: Normalised usage; estimated_cost is null when any call was unpriced.
    usage: dict | None = None
    started_at: datetime
    finished_at: datetime | None
    file_changes: list[FileChangeRead]
    test_results: list[TestResultRead]
