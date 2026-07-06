import pytest

from app.agent.workspace import Workspace, WorkspaceError
from app.core.config import settings
from app.core.enums import ChangeType


@pytest.fixture
def workspace():
    ws = Workspace.create_from(settings.sample_repo_path)
    yield ws
    ws.cleanup()


def test_create_copies_sample_repo(workspace: Workspace):
    files = workspace.list_files()
    assert "calculator.py" in files
    assert "tests/test_calculator.py" in files


def test_create_missing_source_raises(tmp_path):
    with pytest.raises(WorkspaceError):
        Workspace.create_from(tmp_path / "nope")


def test_read_write_delete(workspace: Workspace):
    workspace.write_file("new_module.py", "X = 1\n")
    assert workspace.read_file("new_module.py") == "X = 1\n"
    workspace.delete_file("new_module.py")
    with pytest.raises(WorkspaceError):
        workspace.read_file("new_module.py")


def test_path_escape_rejected(workspace: Workspace):
    with pytest.raises(WorkspaceError):
        workspace.read_file("../outside.txt")
    with pytest.raises(WorkspaceError):
        workspace.write_file("../../etc/evil", "boom")


def test_compute_changes_detects_all_types(workspace: Workspace):
    workspace.write_file("brand_new.py", "print('hi')\n")
    workspace.write_file(
        "calculator.py", workspace.read_file("calculator.py") + "\n# touched\n"
    )
    workspace.delete_file("string_utils.py")

    changes = {c.path: c for c in workspace.compute_changes()}
    assert changes["brand_new.py"].change_type == ChangeType.create
    assert changes["calculator.py"].change_type == ChangeType.modify
    assert changes["string_utils.py"].change_type == ChangeType.delete
    assert "+# touched" in changes["calculator.py"].diff
    assert changes["calculator.py"].diff.startswith("--- a/calculator.py")


def test_no_changes_means_empty_list(workspace: Workspace):
    assert workspace.compute_changes() == []
