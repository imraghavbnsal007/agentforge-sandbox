"""The task and run state machine.

Before Phase 7, status was assigned directly in eleven places across three
services with nothing checking the result. This module makes every transition
explicit and rejectable, so an illegal move fails loudly instead of silently
corrupting history.

Two rules hold everywhere:

  * **terminal states are immutable** — a completed, cancelled or rejected run
    is never rewritten; a retry creates a *new* run instead;
  * **task and run states cannot contradict each other** — `reconcile()` maps a
    run's outcome onto the task, so the pair always agrees.
"""

from app.core.enums import RunStage, RunStatus, TaskStatus

# ---------------------------------------------------------------- tasks --

#: Legal task transitions. A key's absence means the state is terminal.
TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.pending: {
        TaskStatus.planning,
        TaskStatus.coding,
        TaskStatus.testing,
        TaskStatus.ready_for_review,
        TaskStatus.completed,
        TaskStatus.failed,
        TaskStatus.cancelled,
    },
    TaskStatus.planning: {
        TaskStatus.coding,
        TaskStatus.testing,
        TaskStatus.ready_for_review,
        TaskStatus.completed,
        TaskStatus.failed,
        TaskStatus.cancelled,
    },
    TaskStatus.coding: {
        TaskStatus.testing,
        TaskStatus.ready_for_review,
        TaskStatus.completed,
        TaskStatus.failed,
        TaskStatus.cancelled,
    },
    TaskStatus.testing: {
        TaskStatus.ready_for_review,
        TaskStatus.completed,
        TaskStatus.failed,
        TaskStatus.cancelled,
    },
    TaskStatus.ready_for_review: {
        TaskStatus.publishing,
        TaskStatus.rejected,
        # Retrying a reviewed task re-runs the agent.
        TaskStatus.pending,
        TaskStatus.cancelled,
    },
    TaskStatus.publishing: {
        TaskStatus.completed,
        # A blocked publish returns to review with the work intact.
        TaskStatus.ready_for_review,
        TaskStatus.publish_failed,
        TaskStatus.failed,
        TaskStatus.cancelled,
    },
    # Recoverable ends: retry re-queues.
    TaskStatus.failed: {TaskStatus.pending},
    TaskStatus.cancelled: {TaskStatus.pending},
    TaskStatus.publish_failed: {TaskStatus.pending, TaskStatus.publishing},
    TaskStatus.rejected: {TaskStatus.pending},
    # Truly terminal.
    TaskStatus.completed: set(),
}

#: States a user may cancel from.
CANCELLABLE_TASK_STATES = {
    TaskStatus.pending,
    TaskStatus.planning,
    TaskStatus.coding,
    TaskStatus.testing,
    TaskStatus.publishing,
}

#: States a user may retry from.
RETRYABLE_TASK_STATES = {
    TaskStatus.failed,
    TaskStatus.cancelled,
    TaskStatus.publish_failed,
    TaskStatus.rejected,
    TaskStatus.ready_for_review,
}

#: A run in one of these is finished; nothing may rewrite it.
TERMINAL_RUN_STATUSES = {
    RunStatus.completed,
    RunStatus.failed,
    RunStatus.cancelled,
    RunStatus.abandoned,
}

TERMINAL_TASK_STATUSES = {
    status for status, allowed in TASK_TRANSITIONS.items() if not allowed
}

# ----------------------------------------------------------------- runs --

RUN_STAGE_ORDER: list[RunStage] = [
    RunStage.queued,
    RunStage.preparing,
    RunStage.cloning,
    RunStage.analysing,
    RunStage.planning,
    RunStage.generating,
    RunStage.testing,
    RunStage.summarising,
    RunStage.awaiting_review,
    RunStage.pushing,
    RunStage.creating_pr,
    RunStage.completed,
]

#: Execution progress per stage. Deliberately stage-weighted rather than a
#: fabricated continuous percentage — we cannot know how far through a model
#: call we are, so we do not pretend to.
STAGE_PROGRESS: dict[RunStage, int] = {
    RunStage.queued: 0,
    RunStage.preparing: 5,
    RunStage.cloning: 10,
    RunStage.analysing: 20,
    RunStage.planning: 35,
    RunStage.generating: 50,
    RunStage.testing: 70,
    RunStage.summarising: 85,
    RunStage.awaiting_review: 100,
    RunStage.completed: 100,
    # Publishing is a separate phase with its own scale; see PUBLISH_PROGRESS.
    RunStage.pushing: 100,
    RunStage.creating_pr: 100,
    RunStage.failed: 100,
    RunStage.cancelled: 100,
}

#: Publish progress is tracked separately so a push does not appear to rewind
#: the agent's own completed work.
PUBLISH_PROGRESS: dict[RunStage, int] = {
    RunStage.pushing: 50,
    RunStage.creating_pr: 80,
    RunStage.completed: 100,
}

#: Stage a run reaches when the task reaches a given status.
TASK_STATUS_TO_STAGE: dict[TaskStatus, RunStage] = {
    TaskStatus.pending: RunStage.queued,
    TaskStatus.planning: RunStage.planning,
    TaskStatus.coding: RunStage.generating,
    TaskStatus.testing: RunStage.testing,
    TaskStatus.ready_for_review: RunStage.awaiting_review,
    TaskStatus.publishing: RunStage.pushing,
    TaskStatus.completed: RunStage.completed,
    TaskStatus.failed: RunStage.failed,
    TaskStatus.cancelled: RunStage.cancelled,
}


class InvalidTransitionError(Exception):
    """A state change that the lifecycle does not permit."""


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    if current == target:
        return True  # idempotent re-assignment
    return target in TASK_TRANSITIONS.get(current, set())


def assert_transition(current: TaskStatus, target: TaskStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(
            f"Task cannot move from {current} to {target}"
        )


def is_terminal_task(status: TaskStatus) -> bool:
    return status in TERMINAL_TASK_STATUSES


def is_terminal_run(status: RunStatus) -> bool:
    return status in TERMINAL_RUN_STATUSES


def is_cancellable(status: TaskStatus) -> bool:
    return status in CANCELLABLE_TASK_STATES


def is_retryable(status: TaskStatus) -> bool:
    return status in RETRYABLE_TASK_STATES


def progress_for(stage: RunStage, publishing: bool = False) -> int:
    """Execution progress for a stage, 0-100.

    Publishing uses its own scale so it never appears to undo generation.
    """
    table = PUBLISH_PROGRESS if publishing else STAGE_PROGRESS
    return table.get(stage, 0)


def advance_progress(previous: int | None, candidate: int) -> int:
    """Progress never moves backwards within a run.

    A retry starts a new run with its own counter, so this only clamps within
    one execution.
    """
    if previous is None:
        return candidate
    return max(previous, candidate)


def reconcile(run_status: RunStatus, tests_green: bool, has_changes: bool,
              is_github: bool) -> TaskStatus:
    """Map a finished run onto the task status it implies.

    Keeping this in one place is what stops the two from contradicting each
    other, which they previously could because each caller decided for itself.
    """
    if run_status == RunStatus.cancelled:
        return TaskStatus.cancelled
    if run_status == RunStatus.abandoned:
        return TaskStatus.failed
    if run_status == RunStatus.failed:
        return TaskStatus.failed
    if is_github and tests_green and has_changes:
        return TaskStatus.ready_for_review
    return TaskStatus.completed
