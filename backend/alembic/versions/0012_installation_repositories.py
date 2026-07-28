"""Cache of repositories granted to each installation (Phase 6C).

Purely additive. This table is a refreshable cache of what GitHub reports —
rows are removed when access is withdrawn, so a row's presence is the local
answer to "does this installation still grant this repository".

Projects intentionally do not foreign-key into this table; they store
GitHub's numeric repository id directly, so the cache can be rebuilt without
cascading into user data.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_installation_repositories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("full_name", sa.String(length=400), nullable=False),
        sa.Column("default_branch", sa.String(length=200), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["github_installations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "github_repository_id",
            name="uq_installation_repository",
        ),
    )
    op.create_index(
        "ix_github_installation_repositories_installation_id",
        "github_installation_repositories",
        ["installation_id"],
    )
    op.create_index(
        "ix_github_installation_repositories_github_repository_id",
        "github_installation_repositories",
        ["github_repository_id"],
    )
    op.create_index(
        "ix_github_installation_repositories_full_name",
        "github_installation_repositories",
        ["full_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_github_installation_repositories_full_name",
        table_name="github_installation_repositories",
    )
    op.drop_index(
        "ix_github_installation_repositories_github_repository_id",
        table_name="github_installation_repositories",
    )
    op.drop_index(
        "ix_github_installation_repositories_installation_id",
        table_name="github_installation_repositories",
    )
    op.drop_table("github_installation_repositories")
