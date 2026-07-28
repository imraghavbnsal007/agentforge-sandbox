"""Real-time execution: run stages, heartbeats, cancellation, event log (Phase 7).

Purely additive. Adds nullable/defaulted columns to `agent_runs` and creates
`task_events`. No existing column is altered or dropped, no row is rewritten,
and every new `agent_runs` column has a server default so historical rows stay
valid without a backfill.

Existing runs get `stage='queued'` and `progress=0`, which is accurate: those
runs predate stage tracking, and their real position is already recorded in
`status` and `log`.

ROLLBACK SAFETY: downgrade drops `task_events` and the new columns. Historical
runs lose only Phase 7 metadata; status, logs, diffs, branch, commit and PR URL
are untouched.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- agent_runs: stage, progress, heartbeat, cancellation, lineage -----
    op.add_column(
        "agent_runs",
        sa.Column(
            "stage", sa.String(length=20), nullable=False, server_default="queued"
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_runs", sa.Column("error_code", sa.String(length=60), nullable=True)
    )
    op.add_column(
        "agent_runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runs", sa.Column("retry_of_run_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "agent_runs",
        sa.Column("model_calls", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_agent_runs_retry_of_run_id_agent_runs",
        "agent_runs",
        "agent_runs",
        ["retry_of_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Finding abandoned runs after a crash: running rows with a stale heartbeat.
    op.create_index(
        "ix_agent_runs_status_heartbeat_at",
        "agent_runs",
        ["status", "heartbeat_at"],
    )

    # -- task_events -------------------------------------------------------
    op.create_table(
        "task_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("safe_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Per-run monotonic ordering, enforced rather than assumed.
        sa.UniqueConstraint(
            "run_id", "sequence_number", name="uq_task_event_run_sequence"
        ),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])
    op.create_index("ix_task_events_run_id", "task_events", ["run_id"])
    op.create_index("ix_task_events_user_id", "task_events", ["user_id"])
    op.create_index("ix_task_events_created_at", "task_events", ["created_at"])
    # The replay query: everything for a task after a cursor.
    op.create_index("ix_task_events_task_id_id", "task_events", ["task_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_task_events_task_id_id", table_name="task_events")
    op.drop_index("ix_task_events_created_at", table_name="task_events")
    op.drop_index("ix_task_events_user_id", table_name="task_events")
    op.drop_index("ix_task_events_run_id", table_name="task_events")
    op.drop_index("ix_task_events_task_id", table_name="task_events")
    op.drop_table("task_events")

    op.drop_index("ix_agent_runs_status_heartbeat_at", table_name="agent_runs")
    op.drop_constraint(
        "fk_agent_runs_retry_of_run_id_agent_runs", "agent_runs", type_="foreignkey"
    )
    for column in (
        "tool_calls",
        "model_calls",
        "retry_of_run_id",
        "cancel_requested_at",
        "heartbeat_at",
        "error_code",
        "progress",
        "stage",
    ):
        op.drop_column("agent_runs", column)
