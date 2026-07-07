"""GitHub PR workflow: project repo config + run publish fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("repo_url", sa.String(length=500), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "default_branch", sa.String(length=100), nullable=False, server_default="main"
        ),
    )
    op.add_column(
        "projects", sa.Column("github_owner", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "projects", sa.Column("github_repo", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "agent_runs", sa.Column("branch_name", sa.String(length=300), nullable=True)
    )
    op.add_column(
        "agent_runs", sa.Column("commit_sha", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "agent_runs", sa.Column("pr_url", sa.String(length=500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "pr_url")
    op.drop_column("agent_runs", "commit_sha")
    op.drop_column("agent_runs", "branch_name")
    op.drop_column("projects", "github_repo")
    op.drop_column("projects", "github_owner")
    op.drop_column("projects", "default_branch")
    op.drop_column("projects", "repo_url")
