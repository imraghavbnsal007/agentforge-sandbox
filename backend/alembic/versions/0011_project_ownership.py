"""Project ownership (Phase 6C).

THE ONE DESTRUCTIVE MIGRATION IN PHASE 6. It drops the global UNIQUE on
projects.name, which currently makes it impossible for two users to register
the same repository, and replaces it with per-owner uniqueness.

Everything happens in a single transaction:

  1. resolve the owner every existing project is assigned to — the local user
     (github_user_id = 0), created here only if no users exist at all;
  2. add user_id / github_installation_id / github_repository_id as NULLABLE;
  3. backfill user_id for every existing row;
  4. promote user_id to NOT NULL — safe only because step 3 just ran;
  5. drop uq_projects_name;
  6. add UNIQUE(user_id, name) and UNIQUE(user_id, github_repository_id).

No row is deleted or rewritten beyond the new user_id column. Tasks, agent
runs, analyses and llm_runs are untouched and stay attached to their projects.

The two GitHub columns remain nullable permanently: that is what keeps
sample-repo projects and AUTH_MODE=local PAT projects legal.

DOWNGRADE WARNING: restoring the global UNIQUE(name) will fail if two users
have registered the same repository by then. That failure is correct — it
refuses to silently discard one of their projects.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors app.models.user.LOCAL_USER_GITHUB_ID. Duplicated deliberately:
# a migration must describe the schema at its point in history, not import
# application code that may drift.
LOCAL_USER_GITHUB_ID = 0
LOCAL_USER_LOGIN = "local"


def _resolve_owner_id(connection) -> int | None:
    """The user every pre-existing project is assigned to.

    Prefers the local user. Falls back to the lowest-id real user when one
    exists (a deployment that already signed someone in). Creates the local
    user only when the table is empty. Returns None when there are no
    projects to own, in which case no user is invented.
    """
    project_count = connection.execute(
        sa.text("SELECT count(*) FROM projects")
    ).scalar_one()

    local_id = connection.execute(
        sa.text("SELECT id FROM users WHERE github_user_id = :gid"),
        {"gid": LOCAL_USER_GITHUB_ID},
    ).scalar_one_or_none()
    if local_id is not None:
        return local_id

    if project_count == 0:
        # Nothing to backfill; do not create an account that is not needed.
        return None

    existing_id = connection.execute(
        sa.text("SELECT id FROM users ORDER BY id LIMIT 1")
    ).scalar_one_or_none()
    if existing_id is not None:
        return existing_id

    return connection.execute(
        sa.text(
            "INSERT INTO users (github_user_id, github_login, display_name) "
            "VALUES (:gid, :login, :name) RETURNING id"
        ),
        {
            "gid": LOCAL_USER_GITHUB_ID,
            "login": LOCAL_USER_LOGIN,
            "name": "Local User",
        },
    ).scalar_one()


def upgrade() -> None:
    connection = op.get_bind()
    owner_id = _resolve_owner_id(connection)

    op.add_column("projects", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("github_installation_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("github_repository_id", sa.BigInteger(), nullable=True),
    )

    if owner_id is not None:
        result = connection.execute(
            sa.text("UPDATE projects SET user_id = :uid WHERE user_id IS NULL"),
            {"uid": owner_id},
        )
        print(f"[0011] assigned {result.rowcount} project(s) to user {owner_id}")

    # Guard: promoting to NOT NULL must never be attempted with orphans left.
    orphans = connection.execute(
        sa.text("SELECT count(*) FROM projects WHERE user_id IS NULL")
    ).scalar_one()
    if orphans:
        raise RuntimeError(
            f"[0011] refusing to continue: {orphans} project(s) still have no "
            "owner. The transaction will roll back; no data has changed."
        )

    op.alter_column("projects", "user_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        "fk_projects_user_id_users", "projects", "users", ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_projects_github_installation_id_github_installations",
        "projects",
        "github_installations",
        ["github_installation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])
    op.create_index(
        "ix_projects_github_installation_id",
        "projects",
        ["github_installation_id"],
    )
    op.create_index(
        "ix_projects_github_repository_id", "projects", ["github_repository_id"]
    )

    # The heart of the migration: global uniqueness becomes per-owner.
    op.drop_constraint("uq_projects_name", "projects", type_="unique")
    op.create_unique_constraint(
        "uq_projects_user_id_name", "projects", ["user_id", "name"]
    )
    op.create_unique_constraint(
        "uq_projects_user_id_github_repository_id",
        "projects",
        ["user_id", "github_repository_id"],
    )


def downgrade() -> None:
    connection = op.get_bind()

    # Fail loudly rather than destroy data: the global constraint cannot be
    # restored if two owners share a project name.
    duplicates = connection.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT name FROM projects "
            "GROUP BY name HAVING count(*) > 1) d"
        )
    ).scalar_one()
    if duplicates:
        raise RuntimeError(
            f"[0011] cannot downgrade: {duplicates} project name(s) are shared "
            "by more than one user. Restoring UNIQUE(name) would require "
            "deleting someone's project. Resolve the duplicates first."
        )

    op.drop_constraint(
        "uq_projects_user_id_github_repository_id", "projects", type_="unique"
    )
    op.drop_constraint("uq_projects_user_id_name", "projects", type_="unique")
    op.create_unique_constraint("uq_projects_name", "projects", ["name"])

    op.drop_index("ix_projects_github_repository_id", table_name="projects")
    op.drop_index("ix_projects_github_installation_id", table_name="projects")
    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_constraint(
        "fk_projects_github_installation_id_github_installations",
        "projects",
        type_="foreignkey",
    )
    op.drop_constraint("fk_projects_user_id_users", "projects", type_="foreignkey")
    op.drop_column("projects", "github_repository_id")
    op.drop_column("projects", "github_installation_id")
    op.drop_column("projects", "user_id")
