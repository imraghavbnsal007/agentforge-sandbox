"""GitClient tests against a local bare repository — no network involved."""

import subprocess
from pathlib import Path

import pytest

from app.agent.workspace import Workspace
from app.services.git_client import GitClient, GitError


def _git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


@pytest.fixture
def origin(tmp_path: Path) -> str:
    """A bare repo seeded with the sample-repo layout; returns its file:// URL."""
    bare = tmp_path / "origin.git"
    _git("init", "--bare", "-b", "main", str(bare))

    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", "-b", "main", str(seed))
    _git("config", "user.name", "seed", cwd=seed)
    _git("config", "user.email", "seed@localhost", cwd=seed)
    (seed / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    tests_dir = seed / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_calculator.py").write_text(
        "from calculator import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    _git("add", "-A", cwd=seed)
    _git("commit", "-m", "seed", cwd=seed)
    _git("push", str(bare), "main", cwd=seed)
    return f"file://{bare}"


async def test_clone_branch_commit_push_roundtrip(origin: str, tmp_path: Path):
    git = GitClient(token="")
    clone = tmp_path / "clone"
    await git.clone(origin, clone, "main")
    assert (clone / "calculator.py").is_file()

    await git.create_branch(clone, "agentforge/task-1-test")
    (clone / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    )
    sha = await git.commit_all(clone, "Add sub")
    assert len(sha) == 40

    await git.push(clone, origin, "agentforge/task-1-test")
    remote_sha = _git(
        "--git-dir", origin.removeprefix("file://"),
        "rev-parse", "refs/heads/agentforge/task-1-test",
    )
    assert remote_sha == sha


async def test_apply_diff_reproduces_all_change_types(origin: str, tmp_path: Path):
    git = GitClient(token="")

    # Produce diffs the same way a run does: edit a workspace, compute changes.
    ws_dir = tmp_path / "ws"
    await git.clone(origin, ws_dir, "main")
    ws = Workspace.from_dir(ws_dir)
    ws.write_file("calculator.py", "def add(a, b):\n    return int(a + b)\n")
    ws.write_file("new_module.py", "X = 1\n")
    ws.delete_file("tests/test_calculator.py")
    diffs = ws.compute_changes()

    # Apply them to a fresh clone, as the publisher does.
    fresh = tmp_path / "fresh"
    await git.clone(origin, fresh, "main")
    for change in diffs:
        await git.apply_diff(fresh, change.diff)

    assert (fresh / "calculator.py").read_text().startswith("def add")
    assert "int(a + b)" in (fresh / "calculator.py").read_text()
    assert (fresh / "new_module.py").read_text() == "X = 1\n"
    assert not (fresh / "tests/test_calculator.py").exists()


async def test_conflicting_diff_fails_loudly(origin: str, tmp_path: Path):
    git = GitClient(token="")
    clone = tmp_path / "c"
    await git.clone(origin, clone, "main")
    stale_diff = (
        "--- a/calculator.py\n"
        "+++ b/calculator.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def add(x, y):  # this line never existed\n"
        "+def add(x, y):\n"
        "     return x + y\n"
    )
    with pytest.raises(GitError, match="git apply failed"):
        await git.apply_diff(clone, stale_diff)


def test_token_never_appears_in_output():
    git = GitClient(token="ghp_supersecret123")
    scrubbed = git._scrub(
        "fatal: could not read https://x:ghp_supersecret123@github.com "
        f"header AUTHORIZATION: basic {git._b64}"
    )
    assert "ghp_supersecret123" not in scrubbed
    assert git._b64 not in scrubbed
    assert "***" in scrubbed


async def test_applying_an_empty_patch_is_refused_clearly():
    """git's own answer to empty input is "No valid patches in input", which
    reads like the patch was malformed rather than simply absent."""
    from pathlib import Path

    from app.services.git_client import GitClient, GitError

    client = GitClient(token="", committer_name="n", committer_email="e")
    for empty in ("", "   ", "\n\n"):
        with pytest.raises(GitError, match="empty patch"):
            await client.apply_diff(Path("/tmp"), empty)
