"""Guardrail tests for the Makefile and backup/restore/reset scripts.

The destructive command `docker compose down -v` must exist in exactly one
place — scripts/reset_db.sh — behind a typed confirmation phrase and an
automatic safety backup. These tests read the ops files from /repo (a
read-only mount in the backend container) or from the repository root when
run on the host.
"""

from pathlib import Path

import pytest


def _repo_root() -> Path:
    container = Path("/repo")
    if (container / "Makefile").is_file():
        return container
    host = Path(__file__).resolve().parents[2]
    if (host / "Makefile").is_file():
        return host
    pytest.skip("repository ops files not available in this environment")


@pytest.fixture(scope="module")
def root() -> Path:
    return _repo_root()


@pytest.fixture(scope="module")
def makefile(root: Path) -> str:
    return (root / "Makefile").read_text()


def _script(root: Path, name: str) -> str:
    path = root / "scripts" / name
    assert path.is_file(), f"{name} is missing"
    return path.read_text()


# -- Makefile ---------------------------------------------------------------


def test_makefile_never_runs_down_with_volumes(makefile: str):
    assert "down -v" not in makefile
    assert "down --volumes" not in makefile


def test_makefile_down_keeps_database(makefile: str):
    down = makefile.split("\ndown:")[1].split("\n\n")[0]
    assert "docker compose down" in down
    assert "-v" not in down


def test_makefile_reset_db_delegates_to_guarded_script(makefile: str):
    reset = makefile.split("\nreset-db:")[1]
    assert "scripts/reset_db.sh" in reset
    assert "sleep" not in reset  # the old 5-second countdown is gone
    assert "down -v" not in reset


def test_makefile_backup_restore_delegate_to_scripts(makefile: str):
    assert "scripts/backup_db.sh" in makefile
    assert "scripts/restore_db.sh" in makefile
    assert "list-backups:" in makefile


# -- Scripts ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["backup_db.sh", "restore_db.sh", "reset_db.sh"]
)
def test_scripts_use_strict_mode(root: Path, name: str):
    assert "set -euo pipefail" in _script(root, name)


def test_only_reset_script_contains_down_v(root: Path):
    assert "down -v" in _script(root, "reset_db.sh")
    assert "down -v" not in _script(root, "backup_db.sh")
    assert "down -v" not in _script(root, "restore_db.sh")


def test_reset_script_requires_typed_confirmation(root: Path):
    text = _script(root, "reset_db.sh")
    assert 'CONFIRM_PHRASE="DELETE ALL AGENTFORGE DATA"' in text
    # The phrase is compared exactly, and a mismatch aborts.
    assert '"$REPLY" != "$CONFIRM_PHRASE"' in text


def test_reset_script_takes_safety_backup_first(root: Path):
    text = _script(root, "reset_db.sh")
    assert "backup_db.sh --auto" in text
    # Compare against the actual command line, not the header comment.
    command_at = text.index("\ndocker compose down -v")
    assert text.index("backup_db.sh --auto") < command_at


def test_backup_script_is_atomic_and_never_overwrites(root: Path):
    text = _script(root, "backup_db.sh")
    assert 'mv "$TMP" "$FINAL"' in text  # temp file then atomic rename
    assert "refusing to overwrite" in text
    assert "MIN_BYTES" in text  # size validation


def test_backup_retention_only_touches_auto_backups(root: Path):
    text = _script(root, "backup_db.sh")
    assert "auto-agentforge-*.sql" in text
    # The manual prefix never appears in a deletion command.
    for line in text.splitlines():
        if "rm " in line and ".sql" in line:
            assert "auto" in line or "$TMP" in line or '"$old"' in line


def test_restore_script_validates_and_backs_up_first(root: Path):
    text = _script(root, "restore_db.sh")
    assert "PostgreSQL database dump" in text  # dump header validation
    assert "backup_db.sh --auto" in text  # pre-restore safety backup
    assert "alembic upgrade head" in text  # migrations after load
    assert "stop backend worker" in text  # nothing writes mid-restore
    assert text.index("backup_db.sh --auto") < text.index("DROP SCHEMA")


def test_gitignore_excludes_dumps_keeps_directory(root: Path):
    gitignore = (root / ".gitignore").read_text()
    assert "backups/*.sql" in gitignore
