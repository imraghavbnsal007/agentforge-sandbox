"""GitHub App installations and the user<->installation link (Phase 6B).

Purely additive: two new tables, no existing table touched. Project ownership
is deliberately NOT part of this migration — that is 0011 in Phase 6C, and it
is gated on a full rehearsal.

No installation access token is ever stored here. Tokens are short-lived,
minted on demand, and cached only in Redis.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_installations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("github_installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(length=200), nullable=False),
        sa.Column("account_type", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("repository_selection", sa.String(length=20), nullable=False),
        # Non-null while GitHub reports the installation suspended.
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        # Non-null once the App is uninstalled. The row is retained so past
        # tasks stay attributable; only future access is blocked.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_github_installations_github_installation_id",
        "github_installations",
        ["github_installation_id"],
        unique=True,
    )
    op.create_index(
        "ix_github_installations_account_login",
        "github_installations",
        ["account_login"],
        unique=False,
    )

    op.create_table(
        "user_github_installations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["github_installations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "installation_id", name="uq_user_github_installation"
        ),
    )
    op.create_index(
        "ix_user_github_installations_user_id",
        "user_github_installations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_github_installations_installation_id",
        "user_github_installations",
        ["installation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_github_installations_installation_id",
        table_name="user_github_installations",
    )
    op.drop_index(
        "ix_user_github_installations_user_id",
        table_name="user_github_installations",
    )
    op.drop_table("user_github_installations")
    op.drop_index(
        "ix_github_installations_account_login", table_name="github_installations"
    )
    op.drop_index(
        "ix_github_installations_github_installation_id",
        table_name="github_installations",
    )
    op.drop_table("github_installations")
