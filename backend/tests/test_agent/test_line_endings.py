"""Diffs have to describe the bytes that are really on disk.

`Path.read_text()` performs universal-newline translation, so a CRLF file was
recorded as LF and every diff computed from it described content that did not
exist. Publishing a cleanup of an IntelliJ project died on exactly this:

    git apply failed: error: patch failed: .idea/WeatherApp.iml:1
    error: .idea/WeatherApp.iml: patch does not apply

These tests run a real `git apply`, because the bug was invisible to any check
that did not.
"""

import subprocess
from pathlib import Path

import pytest

from app.agent.workspace import Workspace

CRLF_XML = b'<?xml version="1.0"?>\r\n<module>\r\n  <component />\r\n</module>\r\n'


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed git repository holding one CRLF file, as Windows leaves it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    # Stop git normalising line endings, so the file on disk stays CRLF.
    _git(root, "config", "core.autocrlf", "false")
    (root / "app.iml").write_bytes(CRLF_XML)
    (root / "keep.txt").write_text("keep\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "initial")
    return root


def _workspace_copy(repo: Path, tmp_path: Path) -> Workspace:
    """A scratch copy of the repository, byte for byte."""
    import shutil

    work = tmp_path / "work"
    shutil.copytree(repo, work)
    shutil.rmtree(work / ".git")
    return Workspace.from_dir(work)


# -- the recording ----------------------------------------------------------


def test_crlf_survives_into_the_snapshot(repo: Path, tmp_path: Path):
    ws = _workspace_copy(repo, tmp_path)
    assert ws._read_raw("app.iml") == CRLF_XML.decode()


def test_the_agent_still_reads_normalised_text(repo: Path, tmp_path: Path):
    """The model should not have to reason about \\r\\n; only the diff must."""
    ws = _workspace_copy(repo, tmp_path)
    assert "\r" not in ws.read_file("app.iml")


# -- the diff actually applying ---------------------------------------------


def test_a_crlf_deletion_diff_applies_to_the_real_repository(
    repo: Path, tmp_path: Path
):
    ws = _workspace_copy(repo, tmp_path)
    ws.delete_path("app.iml")
    diff = {c.path: c.diff for c in ws.compute_changes()}["app.iml"]

    result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn"],
        cwd=repo, input=diff, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (repo / "app.iml").exists()


def test_a_crlf_edit_diff_applies_to_the_real_repository(
    repo: Path, tmp_path: Path
):
    ws = _workspace_copy(repo, tmp_path)
    ws.write_file("app.iml", ws.read_file("app.iml").replace("<component />", "<c2 />"))
    diff = {c.path: c.diff for c in ws.compute_changes()}["app.iml"]

    result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn"],
        cwd=repo, input=diff, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert b"<c2 />" in (repo / "app.iml").read_bytes()


# -- editing must not rewrite every line ------------------------------------


def test_editing_a_crlf_file_keeps_its_line_endings(repo: Path, tmp_path: Path):
    """Models write LF. Rewriting a CRLF file with LF changes every line in
    it, burying a one-line edit in a whole-file diff."""
    ws = _workspace_copy(repo, tmp_path)
    ws.write_file("app.iml", ws.read_file("app.iml").replace("<component />", "<c2 />"))

    raw = (ws.root / "app.iml").read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")

    diff = {c.path: c.diff for c in ws.compute_changes()}["app.iml"]
    changed = [
        line for line in diff.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert len(changed) == 2, f"expected one line replaced, got:\n{diff}"


def test_a_new_file_is_written_with_plain_lf(repo: Path, tmp_path: Path):
    """Only *existing* files keep their endings; nothing invents CRLF."""
    ws = _workspace_copy(repo, tmp_path)
    ws.write_file("new.py", "a = 1\nb = 2\n")
    assert (ws.root / "new.py").read_bytes() == b"a = 1\nb = 2\n"


def test_an_lf_file_is_untouched_by_any_of_this(repo: Path, tmp_path: Path):
    ws = _workspace_copy(repo, tmp_path)
    ws.write_file("keep.txt", "changed\n")
    assert (ws.root / "keep.txt").read_bytes() == b"changed\n"
