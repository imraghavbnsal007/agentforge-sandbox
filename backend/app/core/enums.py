from enum import StrEnum


class TaskStatus(StrEnum):
    """Task lifecycle.

    Existing values are preserved verbatim so historical rows keep their
    meaning: `pending` is the queued state and `rejected` is the reviewer's
    decline. Phase 7 adds `cancelled` and `publish_failed`, which previously
    had to masquerade as `failed` and `ready_for_review`.
    """

    pending = "pending"
    planning = "planning"
    coding = "coding"
    testing = "testing"
    ready_for_review = "ready_for_review"
    publishing = "publishing"
    rejected = "rejected"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    publish_failed = "publish_failed"


class RunStatus(StrEnum):
    """Coarse run outcome. `stage` carries the fine-grained position."""

    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    abandoned = "abandoned"


class RunStage(StrEnum):
    """Where a run actually is.

    Ordered as the pipeline executes; `STAGE_PROGRESS` in
    app/core/task_state.py assigns each a weight.
    """

    queued = "queued"
    preparing = "preparing"
    cloning = "cloning"
    analysing = "analysing"
    planning = "planning"
    generating = "generating"
    testing = "testing"
    summarising = "summarising"
    awaiting_review = "awaiting_review"
    pushing = "pushing"
    creating_pr = "creating_pr"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ErrorCode(StrEnum):
    """Safe, typed failure reasons.

    The backend stores the code; the frontend maps it to a message and a
    recommended action. Raw exception text is never shown to a user.
    """

    authentication_required = "authentication_required"
    repository_access_lost = "repository_access_lost"
    installation_suspended = "installation_suspended"
    credential_resolution_failed = "credential_resolution_failed"
    clone_failed = "clone_failed"
    patch_failed = "patch_failed"
    provider_unavailable = "provider_unavailable"
    provider_rate_limited = "provider_rate_limited"
    context_limit_exceeded = "context_limit_exceeded"
    tool_failed = "tool_failed"
    test_failed = "test_failed"
    cancelled = "cancelled"
    worker_interrupted = "worker_interrupted"
    push_failed = "push_failed"
    pull_request_failed = "pull_request_failed"
    internal_error = "internal_error"


class TaskEventType(StrEnum):
    """Event kinds published to the live stream and persisted for replay."""

    task_queued = "task_queued"
    run_started = "run_started"
    stage_changed = "stage_changed"
    progress = "progress"
    tool_started = "tool_started"
    tool_completed = "tool_completed"
    tests_started = "tests_started"
    tests_completed = "tests_completed"
    file_changed = "file_changed"
    cost_updated = "cost_updated"
    warning = "warning"
    run_failed = "run_failed"
    run_cancelled = "run_cancelled"
    review_ready = "review_ready"
    publish_started = "publish_started"
    branch_pushed = "branch_pushed"
    pr_created = "pr_created"
    publish_failed = "publish_failed"
    heartbeat = "heartbeat"


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
