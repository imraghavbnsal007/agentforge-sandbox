"""Nullable enrichment_warning on project_analyses: deterministic analysis
succeeded but AI enrichment failed.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_analyses",
        sa.Column("enrichment_warning", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_analyses", "enrichment_warning")
