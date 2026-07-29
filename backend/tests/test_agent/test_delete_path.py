"""Deleting groups of files in one call.

The gap this closes: the agent had only `delete_file`, one path at a time.
Asked to remove `.gradle`, `.idea` and `__pycache__` it was told "File not
found" (they are directories), fell back to deleting files individually, and
burned its whole turn budget — see runs 16 and 17 (2026-07-29).
"""

from pathlib import Path

import pytest

from app.agent.workspace import (
    MAX_DELETIONS_PER_CALL,
    Workspace,
    WorkspaceError,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    (tmp_path / "app").mkdir()
    (tmp_path / "app/main.py").write_text("print('hi')\n")
    (tmp_path / "app/__pycache__").mkdir()
    (tmp_path / "app/__pycache__/main.cpython-312.pyc").write_bytes(b"\x00cached")
    (tmp_path / ".idea").mkdir()
    (tmp_path / ".idea/workspace.xml").write_text("<xml/>")
    (tmp_path / ".gradle/5.6.4/executionHistory").mkdir(parents=True)
    (tmp_path / ".gradle/5.6.4/executionHistory/history.bin").write_bytes(b"\x00")
    (tmp_path / ".gradle/5.6.4/fileChanges").mkdir(parents=True)
    (tmp_path / ".gradle/5.6.4/fileChanges/last-build.bin").write_bytes(b"\x00")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / "db.sqlite3").write_bytes(b"\x00sqlite")
    return Workspace.from_dir(tmp_path)


# -- the whole point --------------------------------------------------------


def test_a_directory_goes_in_one_call(workspace: Workspace):
    deleted = workspace.delete_path(".gradle")

    assert len(deleted) == 2
    assert not (workspace.root / ".gradle").exists()


def test_a_glob_spans_directories(workspace: Workspace):
    deleted = workspace.delete_path("**/*.pyc")

    assert deleted == ["app/__pycache__/main.cpython-312.pyc"]
    assert (workspace.root / "app/main.py").exists()


def test_pycache_directories_go_by_glob(workspace: Workspace):
    workspace.delete_path("**/__pycache__")
    assert not (workspace.root / "app/__pycache__").exists()


def test_a_single_file_still_works(workspace: Workspace):
    assert workspace.delete_path("db.sqlite3") == ["db.sqlite3"]


def test_emptied_directories_do_not_linger(workspace: Workspace):
    """A repository with empty husks left behind does not look cleaned."""
    workspace.delete_path(".gradle/5.6.4/executionHistory/history.bin")
    assert not (workspace.root / ".gradle/5.6.4/executionHistory").exists()


# -- what it refuses --------------------------------------------------------


def test_git_is_never_deletable(workspace: Workspace):
    """It holds the history every diff in the run is computed against."""
    with pytest.raises(WorkspaceError):
        workspace.delete_path(".git")
    assert (workspace.root / ".git/HEAD").exists()


def test_a_glob_sweeping_the_repository_spares_git(workspace: Workspace):
    workspace.delete_path("**/*")
    assert (workspace.root / ".git/HEAD").exists()


@pytest.mark.parametrize("pattern", [".", "./", "*", "**", "**/"])
def test_deleting_the_whole_repository_is_refused(workspace: Workspace, pattern):
    with pytest.raises(WorkspaceError, match="whole repository"):
        workspace.delete_path(pattern)


@pytest.mark.parametrize("pattern", ["../secrets", "/etc/passwd", "app/../../x"])
def test_paths_outside_the_workspace_are_refused(workspace: Workspace, pattern):
    with pytest.raises(WorkspaceError):
        workspace.delete_path(pattern)


def test_a_symlink_out_of_the_workspace_is_not_followed(
    workspace: Workspace, tmp_path: Path
):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("do not touch")
    (workspace.root / "link.txt").symlink_to(outside)

    with pytest.raises(WorkspaceError):
        workspace.delete_path("link.txt")
    assert outside.read_text() == "do not touch"


def test_an_empty_pattern_is_refused(workspace: Workspace):
    with pytest.raises(WorkspaceError):
        workspace.delete_path("   ")


def test_a_pattern_matching_nothing_says_so(workspace: Workspace):
    with pytest.raises(WorkspaceError, match="Nothing to delete"):
        workspace.delete_path("**/*.rs")


def test_an_oversized_match_is_refused_rather_than_obeyed(tmp_path: Path):
    """A mistyped wildcard must not quietly empty the repository."""
    bulk = tmp_path / "bulk"
    bulk.mkdir()
    for i in range(MAX_DELETIONS_PER_CALL + 1):
        (bulk / f"f{i}.txt").write_text("x")
    workspace = Workspace.from_dir(tmp_path)

    with pytest.raises(WorkspaceError, match="narrow it"):
        workspace.delete_path("bulk")
    assert len(list(bulk.iterdir())) == MAX_DELETIONS_PER_CALL + 1


# -- the message that started it all ----------------------------------------


def test_delete_file_on_a_directory_points_at_delete_path(workspace: Workspace):
    """"File not found" for a directory is what sent the agent file-by-file."""
    with pytest.raises(WorkspaceError, match="use delete_path"):
        workspace.delete_file(".gradle")


# -- deletions have to survive as far as the diff ---------------------------


def test_removing_a_cache_shows_up_as_a_change(workspace: Workspace):
    """Invisible in the snapshot meant deleted-but-not-in-the-pull-request."""
    workspace.delete_path("**/__pycache__")

    changed = {c.path for c in workspace.compute_changes()}
    assert "app/__pycache__/main.cpython-312.pyc" in changed
