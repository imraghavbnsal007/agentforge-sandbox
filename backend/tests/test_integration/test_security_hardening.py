"""Security properties asserted end to end.

Covers the input-handling and credential-hygiene guarantees that are easy to
regress silently: no injection through user-controlled strings, no traversal
out of a workspace, and no credential reaching anywhere it must not.
"""

import subprocess
from pathlib import Path

import pytest

from app.agent.workspace import Workspace
from app.core.config import settings
from app.core.security import csrf_token_matches
from app.models import Task
from app.services.git_client import GitClient
from app.services.github_app_api import redact_secrets
from app.services.github_config import parse_github_url
from app.services.publisher import branch_name_for


# -- branch name sanitisation ----------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "; rm -rf /",
        "$(curl evil.example)",
        "`whoami`",
        "../../etc/passwd",
        "--upload-pack=evil",
        "feature && cat /etc/shadow",
        "a\nb\rc",
        "réfacteur ünïcode",
        "'; DROP TABLE projects; --",
        "|" * 50,
    ],
)
def test_branch_names_are_reduced_to_a_safe_slug(title: str):
    """Task titles are user input and reach a git command line."""
    task = Task(id=7, project_id=1, title=title, request="r")
    branch = branch_name_for(task)

    assert branch.startswith("agentforge/task-7-")
    slug = branch.removeprefix("agentforge/task-7-")
    # Only lowercase alphanumerics and hyphens survive.
    assert all(ch.isalnum() and ch.islower() or ch == "-" for ch in slug), slug
    for dangerous in ("..", "/", "\\", ";", "$", "`", "|", "&", "\n", "\r"):
        assert dangerous not in slug


def test_empty_title_still_produces_a_valid_branch():
    branch = branch_name_for(Task(id=1, project_id=1, title="!!!", request="r"))
    assert branch == "agentforge/task-1-change"


def test_branch_name_length_is_bounded():
    branch = branch_name_for(
        Task(id=1, project_id=1, title="x" * 500, request="r")
    )
    assert len(branch.removeprefix("agentforge/task-1-")) <= 40


# -- repository URL validation ---------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/owner/repo",
        "http://github.com/owner/repo",
        "git@github.com:owner/repo.git",
        "https://github.com/owner/repo/../../../etc",
        "file:///etc/passwd",
        "https://github.com@evil.example/o/r",
        "ssh://github.com/o/r",
        "javascript:alert(1)",
    ],
)
def test_only_https_github_urls_are_accepted(url: str):
    """SSRF and host-confusion defence for local-mode registration."""
    from app.core.exceptions import InvalidInputError

    with pytest.raises(InvalidInputError):
        parse_github_url(url)


def test_a_valid_github_url_parses():
    assert parse_github_url("https://github.com/octocat/hello") == (
        "octocat",
        "hello",
    )


# -- workspace path traversal ----------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "../escape.txt",
        "../../etc/passwd",
        "a/../../../outside.txt",
        "/etc/passwd",
    ],
)
def test_workspace_refuses_paths_outside_its_root(tmp_path: Path, rel_path: str):
    """An agent-supplied path must not escape the scratch workspace."""
    root = tmp_path / "ws"
    root.mkdir()
    (root / "inside.txt").write_text("ok")
    workspace = Workspace.from_dir(root)

    with pytest.raises(Exception):
        workspace.write_file(rel_path, "pwned")

    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "outside.txt").exists()


def test_workspace_allows_a_normal_relative_path(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    workspace = Workspace.from_dir(root)
    workspace.write_file("pkg/module.py", "x = 1\n")
    assert (root / "pkg" / "module.py").read_text() == "x = 1\n"


# -- credential hygiene -----------------------------------------------------


def test_secret_shapes_are_redacted():
    for secret in (
        "ghs_installationtoken12345",
        "gho_usertoken1234567890",
        "ghp_personalaccesstoken12",
        "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiIxIn0.c2lnbmF0dXJl",
    ):
        assert secret not in redact_secrets(f"failed: {secret}")


async def test_git_never_writes_credentials_to_disk(tmp_path: Path):
    """The per-command header must leave nothing behind in the clone."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", "."],
        cwd=remote, check=True, capture_output=True,
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    for args in (
        ["git", "init", "--initial-branch=main", "."],
        ["git", "config", "user.name", "S"],
        ["git", "config", "user.email", "s@e.com"],
    ):
        subprocess.run(args, cwd=seed, check=True, capture_output=True)
    (seed / "f.txt").write_text("x")
    for args in (
        ["git", "add", "-A"],
        ["git", "commit", "-m", "i"],
        ["git", "remote", "add", "origin", str(remote)],
        ["git", "push", "origin", "main"],
    ):
        subprocess.run(args, cwd=seed, check=True, capture_output=True)

    token = "ghs_super_secret_installation_token"
    dest = tmp_path / "clone"
    await GitClient(token=token).clone(str(remote), dest, "main")

    # Nothing under .git may contain it.
    for path in (dest / ".git").rglob("*"):
        if path.is_file():
            try:
                if token in path.read_text(errors="ignore"):
                    pytest.fail(f"token found in {path}")
            except (OSError, UnicodeDecodeError):
                continue


# -- CSRF -------------------------------------------------------------------


class _Request:
    def __init__(self, token: str) -> None:
        self.headers = {"X-CSRF-Token": token} if token else {}


def test_csrf_requires_an_exact_match():
    assert csrf_token_matches(_Request("abc123"), "abc123") is True
    assert csrf_token_matches(_Request("abc124"), "abc123") is False
    assert csrf_token_matches(_Request(""), "abc123") is False
    assert csrf_token_matches(_Request("abc123"), "") is False


def test_csrf_rejects_a_prefix():
    """Guards against a non-constant-time comparison being reintroduced."""
    assert csrf_token_matches(_Request("abc"), "abc123") is False


# -- webhook signature ------------------------------------------------------


def test_webhook_signature_requires_the_prefix_and_exact_digest():
    import hashlib
    import hmac

    from app.api.routes.github_webhooks import verify_signature

    body = b'{"action":"created"}'
    secret = "s3cret"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_signature(body, f"sha256={digest}", secret) is True
    assert verify_signature(body, digest, secret) is False  # no prefix
    assert verify_signature(body, f"sha256={digest[:-1]}0", secret) is False
    assert verify_signature(body, "", secret) is False
    assert verify_signature(b'{"action":"deleted"}', f"sha256={digest}", secret) is False


# -- no PAT fallback --------------------------------------------------------


def test_allowlist_does_not_apply_in_github_app_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    """The installation grant is the allowlist; a global list would be
    meaningless across users."""
    from app.core.enums import AuthMode
    from app.services.github_config import check_repo_allowed

    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_allowed_repos", "someone/else")
    # Must not raise.
    check_repo_allowed("octocat", "hello")


def test_allowlist_still_applies_in_local_mode(monkeypatch: pytest.MonkeyPatch):
    from app.core.enums import AuthMode
    from app.core.exceptions import ForbiddenError
    from app.services.github_config import check_repo_allowed

    monkeypatch.setattr(settings, "auth_mode", AuthMode.local)
    monkeypatch.setattr(settings, "github_allowed_repos", "someone/else")
    with pytest.raises(ForbiddenError):
        check_repo_allowed("octocat", "hello")
