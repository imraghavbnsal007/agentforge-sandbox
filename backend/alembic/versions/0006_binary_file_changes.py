"""Binary file changes: metadata-only storage (is_binary, size, hash)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "file_changes",
        sa.Column("is_binary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("file_changes", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.add_column(
        "file_changes", sa.Column("content_hash", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("file_changes", "content_hash")
    op.drop_column("file_changes", "size_bytes")
    op.drop_column("file_changes", "is_binary")
