"""Deep repository intelligence: semantic fields, SQL schema, health score,
richer suggestions

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_analyses", sa.Column("project_type", sa.String(length=120), nullable=True)
    )
    op.add_column("project_analyses", sa.Column("entry_points", sa.JSON(), nullable=True))
    op.add_column("project_analyses", sa.Column("api_routes", sa.JSON(), nullable=True))
    op.add_column("project_analyses", sa.Column("repo_map", sa.JSON(), nullable=True))
    op.add_column("project_analyses", sa.Column("sql_schema", sa.JSON(), nullable=True))
    op.add_column("project_analyses", sa.Column("schema_summary", sa.Text(), nullable=True))
    op.add_column("project_analyses", sa.Column("health_score", sa.Integer(), nullable=True))
    op.add_column(
        "project_analyses", sa.Column("health_breakdown", sa.JSON(), nullable=True)
    )
    op.add_column(
        "repo_improvement_suggestions",
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="medium"),
    )
    op.add_column(
        "repo_improvement_suggestions",
        sa.Column("reasoning", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "repo_improvement_suggestions",
        sa.Column("effort", sa.String(length=20), nullable=False, server_default="medium"),
    )


def downgrade() -> None:
    op.drop_column("repo_improvement_suggestions", "effort")
    op.drop_column("repo_improvement_suggestions", "reasoning")
    op.drop_column("repo_improvement_suggestions", "confidence")
    op.drop_column("project_analyses", "health_breakdown")
    op.drop_column("project_analyses", "health_score")
    op.drop_column("project_analyses", "schema_summary")
    op.drop_column("project_analyses", "sql_schema")
    op.drop_column("project_analyses", "repo_map")
    op.drop_column("project_analyses", "api_routes")
    op.drop_column("project_analyses", "entry_points")
    op.drop_column("project_analyses", "project_type")
