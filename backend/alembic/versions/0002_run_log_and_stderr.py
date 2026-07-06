"""Add agent_runs.log and test_results.stderr

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("log", sa.Text(), nullable=True))
    op.add_column(
        "test_results",
        sa.Column("stderr", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("test_results", "stderr")
    op.drop_column("agent_runs", "log")
