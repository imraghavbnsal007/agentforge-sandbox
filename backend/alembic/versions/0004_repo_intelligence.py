"""Repository intelligence: analyses, file summaries, improvement suggestions

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("languages", sa.JSON(), nullable=True),
        sa.Column("frameworks", sa.JSON(), nullable=True),
        sa.Column("dependencies", sa.JSON(), nullable=True),
        sa.Column("package_manager", sa.String(length=50), nullable=True),
        sa.Column("build_command", sa.String(length=300), nullable=True),
        sa.Column("test_command", sa.String(length=300), nullable=True),
        sa.Column("architecture_notes", sa.Text(), nullable=True),
        sa.Column("risk_areas", sa.Text(), nullable=True),
        sa.Column("analysis_logs", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_analyses_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_analyses")),
    )
    op.create_index(
        op.f("ix_project_analyses_project_id"), "project_analyses", ["project_id"]
    )
    op.create_table(
        "repo_file_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("importance_score", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["project_analyses.id"],
            name=op.f("fk_repo_file_summaries_analysis_id_project_analyses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repo_file_summaries")),
    )
    op.create_index(
        op.f("ix_repo_file_summaries_analysis_id"), "repo_file_summaries", ["analysis_id"]
    )
    op.create_table(
        "repo_improvement_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("analysis_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("related_files", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["project_analyses.id"],
            name=op.f("fk_repo_improvement_suggestions_analysis_id_project_analyses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repo_improvement_suggestions")),
    )
    op.create_index(
        op.f("ix_repo_improvement_suggestions_analysis_id"),
        "repo_improvement_suggestions",
        ["analysis_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_repo_improvement_suggestions_analysis_id"),
        table_name="repo_improvement_suggestions",
    )
    op.drop_table("repo_improvement_suggestions")
    op.drop_index(
        op.f("ix_repo_file_summaries_analysis_id"), table_name="repo_file_summaries"
    )
    op.drop_table("repo_file_summaries")
    op.drop_index(op.f("ix_project_analyses_project_id"), table_name="project_analyses")
    op.drop_table("project_analyses")
