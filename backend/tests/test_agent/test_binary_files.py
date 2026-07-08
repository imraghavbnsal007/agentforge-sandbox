"""Regression tests for binary files in the diff pipeline.

Task 11 crashed with PostgreSQL CharacterNotInRepertoireError (0x00) when the
agent deleted 'DataBase Project.zip' and the ZIP's bytes landed in the
unified diff. Binary changes must be metadata-only.
"""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.mock_runner import MockRunner
from app.agent.workspace import Workspace, WorkspaceError
from app.core.enums import ChangeType, RunStatus, TaskStatus
from app.models import Task
from app.services.run_service import RunService
from tests.test_services.test_run_service import FakeExecutor

# Realistic magic bytes, all containing NULs.
ZIP_BYTES = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 64 + b"PK\x05\x06" + b"\x00" * 18
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 32
PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nstream\n" + b"\x00\x01\x02" * 20


@pytest.fixture
def binary_repo(tmp_path: Path) -> Path:
    (tmp_path / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "archive.zip").write_bytes(ZIP_BYTES)
    (tmp_path / "logo.png").write_bytes(PNG_BYTES)
    (tmp_path / "manual.pdf").write_bytes(PDF_BYTES)
    return tmp_path


def test_unchanged_binaries_produce_no_changes(binary_repo: Path):
    ws = Workspace.from_dir(binary_repo)
    assert ws.compute_changes() == []


@pytest.mark.parametrize("name", ["archive.zip", "logo.png", "manual.pdf"])
def test_binary_delete_is_metadata_only(binary_repo: Path, name: str):
    ws = Workspace.from_dir(binary_repo)
    original_size = (binary_repo / name).stat().st_size
    ws.delete_file(name)

    changes = {c.path: c for c in ws.compute_changes()}
    change = changes[name]
    assert change.change_type == ChangeType.delete
    assert change.is_binary is True
    assert change.diff == ""
    assert change.size_bytes == original_size
    assert len(change.content_hash) == 64
    assert "\x00" not in change.diff


def test_new_binary_is_metadata_only(binary_repo: Path):
    ws = Workspace.from_dir(binary_repo)
    (binary_repo / "generated.png").write_bytes(PNG_BYTES)

    changes = {c.path: c for c in ws.compute_changes()}
    change = changes["generated.png"]
    assert change.change_type == ChangeType.create
    assert change.is_binary is True
    assert change.diff == ""
    assert change.size_bytes == len(PNG_BYTES)


def test_modified_binary_is_metadata_only(binary_repo: Path):
    ws = Workspace.from_dir(binary_repo)
    (binary_repo / "archive.zip").write_bytes(ZIP_BYTES + b"\x00extra")

    changes = {c.path: c for c in ws.compute_changes()}
    change = changes["archive.zip"]
    assert change.change_type == ChangeType.modify
    assert change.is_binary is True
    assert change.diff == ""


def test_no_diff_ever_contains_nul(binary_repo: Path):
    ws = Workspace.from_dir(binary_repo)
    ws.delete_file("archive.zip")
    ws.delete_file("logo.png")
    ws.write_file("calculator.py", "def add(a, b):\n    return int(a + b)\n")
    (binary_repo / "new.pdf").write_bytes(PDF_BYTES)

    for change in ws.compute_changes():
        assert "\x00" not in change.diff, change.path


def test_read_file_refuses_binaries(binary_repo: Path):
    ws = Workspace.from_dir(binary_repo)
    for name in ("archive.zip", "logo.png", "manual.pdf"):
        with pytest.raises(WorkspaceError, match="binary"):
            ws.read_file(name)


def test_text_file_with_nul_bytes_is_treated_as_binary(tmp_path: Path):
    # Extension says text, content says binary — the sniff must win.
    (tmp_path / "weird.txt").write_bytes(b"looks like text\x00but is not")
    ws = Workspace.from_dir(tmp_path)
    with pytest.raises(WorkspaceError, match="binary"):
        ws.read_file("weird.txt")
    ws.delete_file("weird.txt")
    change = ws.compute_changes()[0]
    assert change.is_binary is True and change.diff == ""


def test_repo_context_omits_binary_content(binary_repo: Path):
    from app.agent.claude_runner import _repo_context

    ws = Workspace.from_dir(binary_repo)
    context = _repo_context(ws)
    assert "\x00" not in context
    assert "PK\x03" not in context
    assert "archive.zip\n(binary file — content omitted)" in context
    assert "def add" in context  # text files still included


class ZipDeletingRunner(MockRunner):
    """Simulates task 11: the agent deletes an archive and writes text files."""

    async def apply_changes(self, title, request, plan, workspace, log):
        workspace.delete_file("archive.zip")
        workspace.write_file("extracted.sql", "CREATE TABLE t (id INT);\n")
        log("mock: deleted archive.zip, created extracted.sql")


async def test_run_pipeline_survives_binary_changes(
    session: AsyncSession, project, binary_repo: Path
) -> None:
    """End-to-end regression: a run that deletes a ZIP must complete and
    store the binary change as metadata."""
    task = Task(project_id=project.id, title="T", request="R")
    session.add(task)
    await session.commit()

    async def factory(_project):
        return Workspace.from_dir(binary_repo)

    run = await RunService(
        session,
        runner=ZipDeletingRunner(delay=0),
        executor=FakeExecutor(),
        workspace_factory=factory,
    ).execute_agent_run(task.id)

    assert run.status == RunStatus.completed
    assert task.status == TaskStatus.completed
    changes = {c.path: c for c in run.file_changes}
    zip_change = changes["archive.zip"]
    assert zip_change.is_binary is True
    assert zip_change.diff == ""
    assert zip_change.size_bytes == len(ZIP_BYTES)
    assert changes["extracted.sql"].is_binary is False
    assert "+CREATE TABLE" in changes["extracted.sql"].diff
    assert "binary file delete: archive.zip" in run.log
