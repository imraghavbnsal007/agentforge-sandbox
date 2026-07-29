"""Record when an agent run stopped before finishing.

Purely additive: one nullable `agent_runs.incomplete_reason` column. No
existing column is altered or dropped, no row is rewritten, and no backfill
is needed — NULL is the correct value for every historical run, which is
what "did not stop early" has always meant.

The column is deliberately separate from `error`. `error` means the run
produced nothing usable; `incomplete_reason` means it produced real changes
that may not be the whole job. Collapsing the two would make a partially
successful run look like a failure.

ROLLBACK SAFETY: downgrade drops the column. Runs lose only the early-stop
warning; status, summary, logs, diffs, branch, commit and PR URL are
untouched, and no other column is read or written by this migration.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("incomplete_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "incomplete_reason")
