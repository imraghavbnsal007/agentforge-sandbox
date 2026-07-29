import difflib
import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.enums import ChangeType

IGNORED = ("__pycache__", ".pytest_cache", ".git", "*.pyc")

#: Never removable, whatever is asked for. `.git` is the repository itself —
#: deleting it would destroy the history every diff is computed against.
PROTECTED_PARTS = frozenset({".git"})

#: Ceiling on a single delete_path call, so a mistyped wildcard cannot
#: quietly empty the repository. Generous on purpose: a Gradle or pip cache
#: runs to hundreds of files and clearing it is a legitimate request.
MAX_DELETIONS_PER_CALL = 2000

# Extensions that are binary by definition (shared vocabulary with repo_facts,
# duplicated here to keep the agent layer import-light).
BINARY_EXTENSIONS = {
    ".zip", ".gz", ".tar", ".tgz", ".7z", ".rar", ".png", ".jpg", ".jpeg",
    ".gif", ".webp", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".mov", ".pyc", ".so", ".dylib", ".dll", ".exe", ".bin",
    ".wasm", ".jar", ".class", ".db", ".sqlite", ".sqlite3", ".parquet",
}


@dataclass
class BinaryInfo:
    """Snapshot marker for a binary file: metadata only, never content."""

    size_bytes: int
    sha256: str


@dataclass
class FileChangeData:
    path: str
    change_type: ChangeType
    diff: str
    is_binary: bool = False
    size_bytes: int | None = None
    content_hash: str | None = None


class WorkspaceError(Exception):
    pass


class Workspace:
    """A scratch copy of the sample repo that one agent run works in.

    Tracks a snapshot of every file at creation time so diffs can be
    computed after the agent edits the copy. All paths are validated to
    stay inside the workspace root.
    """

    def __init__(self, root: Path, snapshot: dict[str, "str | BinaryInfo"]) -> None:
        self.root = root
        self._snapshot = snapshot

    @classmethod
    def create_from(cls, source: str | Path) -> "Workspace":
        source = Path(source)
        if not source.is_dir():
            raise WorkspaceError(f"Sample repo not found at {source}")
        root = Path(tempfile.mkdtemp(prefix="agentforge-ws-"))
        shutil.copytree(
            source, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*IGNORED)
        )
        return cls.from_dir(root)

    @classmethod
    def from_dir(cls, root: Path) -> "Workspace":
        """Wrap an already-populated directory (e.g. a git clone) and snapshot it.

        Binary files are snapshotted as metadata (size + hash) only — their
        content is never decoded and can never reach a text diff.
        """
        ws = cls(Path(root), {})
        ws._snapshot = {path: ws._snapshot_entry(path) for path in ws.list_files()}
        return ws

    def _snapshot_entry(self, rel_path: str) -> "str | BinaryInfo":
        if self.is_binary(rel_path):
            return self._binary_info(rel_path)
        return self.read_file(rel_path)

    def is_binary(self, rel_path: str) -> bool:
        target = self._resolve(rel_path)
        if not target.is_file():
            return False
        if target.suffix.lower() in BINARY_EXTENSIONS:
            return True
        try:
            with open(target, "rb") as fh:
                return b"\0" in fh.read(8192)
        except OSError:
            return True

    def _binary_info(self, rel_path: str) -> BinaryInfo:
        target = self._resolve(rel_path)
        digest = hashlib.sha256()
        with open(target, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return BinaryInfo(size_bytes=target.stat().st_size, sha256=digest.hexdigest())

    def _resolve(self, rel_path: str) -> Path:
        resolved = (self.root / rel_path).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise WorkspaceError(f"Path escapes the workspace: {rel_path!r}")
        return resolved

    def list_files(self) -> list[str]:
        files = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(self.root).parts
            # `.git` is repository machinery, never content. `__pycache__`
            # was hidden here too, which meant a repository that had
            # committed it could never be cleaned: the files were invisible
            # to the snapshot, so deleting them produced no diff and the
            # change was silently dropped before it reached a pull request.
            if any(part in PROTECTED_PARTS for part in parts):
                continue
            files.append(path.relative_to(self.root).as_posix())
        return sorted(files)

    def read_file(self, rel_path: str) -> str:
        target = self._resolve(rel_path)
        if not target.is_file():
            raise WorkspaceError(f"File not found: {rel_path!r}")
        if self.is_binary(rel_path):
            raise WorkspaceError(
                f"{rel_path!r} is a binary file and cannot be read as text"
            )
        # NUL bytes are rejected by PostgreSQL text columns; strip defensively
        # even for files that pass the binary sniff.
        return target.read_text(errors="replace").replace("\x00", "")

    def write_file(self, rel_path: str, content: str) -> None:
        target = self._resolve(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def delete_file(self, rel_path: str) -> None:
        target = self._resolve(rel_path)
        if target.is_dir():
            # The old message here was "File not found", which is how an
            # agent asked to remove `.gradle` ended up deleting it one file
            # at a time and running out of turns.
            raise WorkspaceError(
                f"{rel_path!r} is a directory — use delete_path to remove it"
            )
        if not target.is_file():
            raise WorkspaceError(f"File not found: {rel_path!r}")
        target.unlink()

    def delete_path(self, pattern: str) -> list[str]:
        """Delete a file, a directory tree, or a glob. Returns what went.

        `delete_file` takes exactly one file, so clearing a build cache cost
        one model turn per file and the edit loop ran out of turns long
        before the repository was clean. "Remove __pycache__ directories,
        *.pyc and .idea" is one operation as far as the request is
        concerned, so it is one operation here.
        """
        pattern = (pattern or "").strip()
        if not pattern:
            raise WorkspaceError("delete_path needs a path or glob pattern")
        if pattern.startswith("/") or Path(pattern).is_absolute():
            raise WorkspaceError(
                f"Path must be relative to the repository: {pattern!r}"
            )
        if pattern.strip("./") in ("", "*", "**"):
            raise WorkspaceError(
                f"Refusing to delete the whole repository ({pattern!r})"
            )

        matched = self._match(pattern)
        files = sorted({f for match in matched for f in self._files_under(match)})
        if not files:
            raise WorkspaceError(f"Nothing to delete matching {pattern!r}")
        if len(files) > MAX_DELETIONS_PER_CALL:
            raise WorkspaceError(
                f"{pattern!r} matches {len(files)} files, over the "
                f"{MAX_DELETIONS_PER_CALL} limit for one call — narrow it"
            )

        deleted = [target.relative_to(self.root).as_posix() for target in files]
        for target in files:
            target.unlink()
        self._prune_empty_dirs()
        return sorted(deleted)

    def _match(self, pattern: str) -> list[Path]:
        """Resolve a literal path or glob to existing paths inside the root."""
        candidates = (
            list(self.root.glob(pattern))
            if any(ch in pattern for ch in "*?[")
            else [self.root / pattern]
        )
        root = self.root.resolve()
        inside = []
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved == root or not resolved.is_relative_to(root):
                raise WorkspaceError(f"Path escapes the workspace: {pattern!r}")
            if candidate.exists():
                inside.append(candidate)
        return inside

    def _files_under(self, target: Path) -> list[Path]:
        """Every deletable file at or beneath a path; protected ones excluded."""
        if self._is_protected(target):
            return []
        if target.is_file() or target.is_symlink():
            return [target]
        return [
            child
            for child in target.rglob("*")
            if child.is_file() and not self._is_protected(child)
        ]

    def _is_protected(self, target: Path) -> bool:
        return any(
            part in PROTECTED_PARTS
            for part in target.relative_to(self.root).parts
        )

    def _prune_empty_dirs(self) -> None:
        """Drop directories left empty by a deletion.

        Without this, removing every file under `.gradle` leaves the empty
        tree behind and the repository does not look cleaned.
        """
        directories = sorted(
            (p for p in self.root.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for directory in directories:
            if self._is_protected(directory):
                continue
            if not any(directory.iterdir()):
                directory.rmdir()

    def compute_changes(self) -> list[FileChangeData]:
        changes = []
        current_files = set(self.list_files())
        all_paths = sorted(current_files | set(self._snapshot))
        for path in all_paths:
            before = self._snapshot.get(path)
            after = self._snapshot_entry(path) if path in current_files else None
            if before == after:
                continue

            if before is None:
                change_type = ChangeType.create
            elif after is None:
                change_type = ChangeType.delete
            else:
                change_type = ChangeType.modify

            # If either side is binary, never build a textual diff — record
            # metadata only, so binary bytes can't reach a text column.
            if isinstance(before, BinaryInfo) or isinstance(after, BinaryInfo):
                info = after if isinstance(after, BinaryInfo) else before
                if not isinstance(info, BinaryInfo):
                    info = None
                changes.append(
                    FileChangeData(
                        path=path,
                        change_type=change_type,
                        diff="",
                        is_binary=True,
                        size_bytes=info.size_bytes if info else None,
                        content_hash=info.sha256 if info else None,
                    )
                )
                continue

            # /dev/null headers for creates/deletes make the diffs valid
            # input for `git apply` at publish time.
            if change_type == ChangeType.create:
                fromfile, tofile = "/dev/null", f"b/{path}"
            elif change_type == ChangeType.delete:
                fromfile, tofile = f"a/{path}", "/dev/null"
            else:
                fromfile, tofile = f"a/{path}", f"b/{path}"
            diff = "".join(
                difflib.unified_diff(
                    (before or "").splitlines(keepends=True),
                    (after or "").splitlines(keepends=True),
                    fromfile=fromfile,
                    tofile=tofile,
                )
            )
            changes.append(FileChangeData(path=path, change_type=change_type, diff=diff))
        return changes

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
