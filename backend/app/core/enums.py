from enum import StrEnum


class TaskStatus(StrEnum):
    pending = "pending"
    planning = "planning"
    coding = "coding"
    testing = "testing"
    ready_for_review = "ready_for_review"
    publishing = "publishing"
    rejected = "rejected"
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


class AuthMode(StrEnum):
    """How AgentForge identifies the caller.

    local      — single-user development: every request resolves to the
                 default local user, no sign-in, PAT + allowlist repo access.
    github_app — public multi-user: GitHub sign-in for identity, GitHub App
                 installations for repository authorisation.
    """

    local = "local"
    github_app = "github_app"


class AnalysisStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
