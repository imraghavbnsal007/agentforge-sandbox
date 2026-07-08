"""Multi-provider architecture: llm_runs table, task overrides, project prefs

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("agent_run_id", sa.Integer(), nullable=True),
        sa.Column("analysis_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("phase", sa.String(length=30), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"],
            name=op.f("fk_llm_runs_project_id_projects"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"],
            name=op.f("fk_llm_runs_agent_run_id_agent_runs"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["project_analyses.id"],
            name=op.f("fk_llm_runs_analysis_id_project_analyses"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_runs")),
    )
    op.create_index(op.f("ix_llm_runs_project_id"), "llm_runs", ["project_id"])
    op.create_index(op.f("ix_llm_runs_agent_run_id"), "llm_runs", ["agent_run_id"])

    op.add_column("tasks", sa.Column("llm_provider", sa.String(length=30), nullable=True))
    op.add_column("tasks", sa.Column("llm_model", sa.String(length=100), nullable=True))
    op.add_column(
        "tasks", sa.Column("execution_profile", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "projects", sa.Column("preferred_provider", sa.String(length=30), nullable=True)
    )
    op.add_column(
        "projects", sa.Column("preferred_model", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "projects",
        sa.Column("preferred_execution_profile", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "preferred_execution_profile")
    op.drop_column("projects", "preferred_model")
    op.drop_column("projects", "preferred_provider")
    op.drop_column("tasks", "execution_profile")
    op.drop_column("tasks", "llm_model")
    op.drop_column("tasks", "llm_provider")
    op.drop_index(op.f("ix_llm_runs_agent_run_id"), table_name="llm_runs")
    op.drop_index(op.f("ix_llm_runs_project_id"), table_name="llm_runs")
    op.drop_table("llm_runs")
