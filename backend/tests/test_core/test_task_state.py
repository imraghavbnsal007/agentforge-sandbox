"""The task state machine.

Before Phase 7 status was assigned in eleven places with nothing checking the
result. These tests pin down what is now legal.
"""

import pytest

from app.core.enums import RunStage, RunStatus, TaskStatus
from app.core.task_state import (
    STAGE_PROGRESS,
    TERMINAL_RUN_STATUSES,
    InvalidTransitionError,
    advance_progress,
    assert_transition,
    can_transition,
    is_cancellable,
    is_retryable,
    is_terminal_run,
    is_terminal_task,
    progress_for,
    reconcile,
)


# -- valid transitions ------------------------------------------------------


@pytest.mark.parametrize(
    "current,target",
    [
        (TaskStatus.pending, TaskStatus.planning),
        (TaskStatus.planning, TaskStatus.coding),
        (TaskStatus.coding, TaskStatus.testing),
        (TaskStatus.testing, TaskStatus.ready_for_review),
        (TaskStatus.ready_for_review, TaskStatus.publishing),
        (TaskStatus.publishing, TaskStatus.completed),
        (TaskStatus.ready_for_review, TaskStatus.rejected),
    ],
)
def test_the_happy_path_is_allowed(current, target):
    assert can_transition(current, target) is True
    assert_transition(current, target)


@pytest.mark.parametrize(
    "current",
    [
        TaskStatus.pending,
        TaskStatus.planning,
        TaskStatus.coding,
        TaskStatus.testing,
        TaskStatus.publishing,
    ],
)
def test_any_active_state_may_be_cancelled(current):
    assert can_transition(current, TaskStatus.cancelled) is True
    assert is_cancellable(current) is True


@pytest.mark.parametrize(
    "current",
    [TaskStatus.failed, TaskStatus.cancelled, TaskStatus.publish_failed,
     TaskStatus.rejected],
)
def test_recoverable_ends_may_be_retried(current):
    assert can_transition(current, TaskStatus.pending) is True
    assert is_retryable(current) is True


def test_a_blocked_publish_returns_to_review():
    """Publishing failures must not lose the generated work."""
    assert can_transition(TaskStatus.publishing, TaskStatus.ready_for_review)
    assert can_transition(TaskStatus.publishing, TaskStatus.publish_failed)


# -- invalid transitions ----------------------------------------------------


@pytest.mark.parametrize(
    "current,target",
    [
        (TaskStatus.completed, TaskStatus.pending),
        (TaskStatus.completed, TaskStatus.planning),
        (TaskStatus.completed, TaskStatus.failed),
        (TaskStatus.pending, TaskStatus.publishing),
        (TaskStatus.planning, TaskStatus.publishing),
        (TaskStatus.cancelled, TaskStatus.completed),
        (TaskStatus.failed, TaskStatus.completed),
        (TaskStatus.rejected, TaskStatus.publishing),
    ],
)
def test_illegal_moves_are_rejected(current, target):
    assert can_transition(current, target) is False
    with pytest.raises(InvalidTransitionError):
        assert_transition(current, target)


def test_completed_is_terminal():
    assert is_terminal_task(TaskStatus.completed) is True
    for target in TaskStatus:
        if target != TaskStatus.completed:
            assert can_transition(TaskStatus.completed, target) is False


def test_reassigning_the_same_status_is_allowed():
    """Idempotent writes must not raise — a retried commit is not an error."""
    for status in TaskStatus:
        assert can_transition(status, status) is True


def test_the_error_names_both_states():
    with pytest.raises(InvalidTransitionError, match="completed.*pending"):
        assert_transition(TaskStatus.completed, TaskStatus.pending)


# -- run terminality --------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [RunStatus.completed, RunStatus.failed, RunStatus.cancelled,
     RunStatus.abandoned],
)
def test_finished_runs_are_terminal(status):
    assert is_terminal_run(status) is True
    assert status in TERMINAL_RUN_STATUSES


def test_a_running_run_is_not_terminal():
    assert is_terminal_run(RunStatus.running) is False


# -- progress ---------------------------------------------------------------


def test_progress_increases_monotonically_through_the_pipeline():
    ordered = [
        RunStage.queued,
        RunStage.preparing,
        RunStage.cloning,
        RunStage.analysing,
        RunStage.planning,
        RunStage.generating,
        RunStage.testing,
        RunStage.summarising,
        RunStage.awaiting_review,
    ]
    values = [STAGE_PROGRESS[stage] for stage in ordered]
    assert values == sorted(values)
    assert values[0] == 0
    assert values[-1] == 100


def test_progress_never_moves_backwards():
    assert advance_progress(70, 35) == 70
    assert advance_progress(35, 70) == 70
    assert advance_progress(None, 20) == 20


def test_publish_progress_is_a_separate_scale():
    """Publishing must not appear to rewind the agent's completed work."""
    assert progress_for(RunStage.pushing, publishing=True) == 50
    assert progress_for(RunStage.creating_pr, publishing=True) == 80
    assert progress_for(RunStage.completed, publishing=True) == 100
    # On the execution scale those stages are already at the end.
    assert progress_for(RunStage.pushing, publishing=False) == 100


def test_unknown_stage_is_zero_not_an_error():
    assert progress_for(RunStage.failed, publishing=True) == 0


# -- reconciliation ---------------------------------------------------------


def test_a_successful_github_run_with_changes_awaits_review():
    assert reconcile(
        RunStatus.completed, tests_green=True, has_changes=True, is_github=True
    ) == TaskStatus.ready_for_review


def test_failing_tests_complete_rather_than_await_review():
    assert reconcile(
        RunStatus.completed, tests_green=False, has_changes=True, is_github=True
    ) == TaskStatus.completed


def test_no_changes_completes():
    assert reconcile(
        RunStatus.completed, tests_green=True, has_changes=False, is_github=True
    ) == TaskStatus.completed


def test_a_sample_repo_run_completes_rather_than_awaiting_review():
    assert reconcile(
        RunStatus.completed, tests_green=True, has_changes=True, is_github=False
    ) == TaskStatus.completed


def test_a_cancelled_run_makes_the_task_cancelled():
    assert reconcile(
        RunStatus.cancelled, tests_green=True, has_changes=True, is_github=True
    ) == TaskStatus.cancelled


def test_an_abandoned_run_makes_the_task_failed():
    assert reconcile(
        RunStatus.abandoned, tests_green=False, has_changes=False, is_github=True
    ) == TaskStatus.failed


def test_reconcile_never_contradicts_a_failed_run():
    assert reconcile(
        RunStatus.failed, tests_green=True, has_changes=True, is_github=True
    ) == TaskStatus.failed
