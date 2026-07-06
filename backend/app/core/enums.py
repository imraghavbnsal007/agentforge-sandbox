from enum import StrEnum


class TaskStatus(StrEnum):
    pending = "pending"
    planning = "planning"
    coding = "coding"
    testing = "testing"
    completed = "completed"
    failed = "failed"


class RunStatus(StrEnum):
    running = "running"
    completed = "completed"
    failed = "failed"


class ChangeType(StrEnum):
    create = "create"
    modify = "modify"
    delete = "delete"


class AgentMode(StrEnum):
    mock = "mock"
    llm = "llm"
