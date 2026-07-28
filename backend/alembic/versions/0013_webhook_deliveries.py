"""Webhook delivery ledger for deduplication (Phase 6E).

Purely additive: one new table, no existing table touched. `projects`,
`github_installations`, `user_github_installations` and the repository cache
are all unaffected, so this migration carries none of 0011's risk.

ROLLBACK SAFETY: downgrade drops only this table. The single consequence is
losing the record of which deliveries have been seen, so a previously
processed delivery could be handled again. That is bounded because every
webhook handler is idempotent — upserts and set-to-value operations, never
increments — so reprocessing converges on the same state.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        # GitHub's X-GitHub-Delivery UUID. The UNIQUE constraint is the
        # deduplication mechanism, not merely an index.
        sa.Column("delivery_id", sa.String(length=100), nullable=False),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=True),
        sa.Column("github_installation_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_webhook_deliveries_delivery_id",
        "webhook_deliveries",
        ["delivery_id"],
        unique=True,
    )
    op.create_index(
        "ix_webhook_deliveries_event", "webhook_deliveries", ["event"]
    )
    op.create_index(
        "ix_webhook_deliveries_github_installation_id",
        "webhook_deliveries",
        ["github_installation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_deliveries_github_installation_id",
        table_name="webhook_deliveries",
    )
    op.drop_index("ix_webhook_deliveries_event", table_name="webhook_deliveries")
    op.drop_index(
        "ix_webhook_deliveries_delivery_id", table_name="webhook_deliveries"
    )
    op.drop_table("webhook_deliveries")
