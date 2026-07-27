"""Users table for GitHub sign-in (Phase 6A).

Purely additive: creates `users` and touches no existing table, so existing
projects, tasks, runs and analyses are unaffected. Project ownership arrives
separately in migration 0011.

The default local user is NOT seeded here. It is created on demand by
UserService.get_or_create_local_user() so that tests (which build the schema
with create_all and never run Alembic) and production take the same path.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        # Immutable GitHub identity. 0 is reserved for the local-mode user;
        # real GitHub ids start at 1.
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("github_login", sa.String(length=100), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
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
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_users_github_user_id", "users", ["github_user_id"], unique=True
    )
    op.create_index("ix_users_github_login", "users", ["github_login"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_github_login", table_name="users")
    op.drop_index("ix_users_github_user_id", table_name="users")
    op.drop_table("users")
