import difflib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.enums import ChangeType

IGNORED = ("__pycache__", ".pytest_cache", ".git", "*.pyc")


@dataclass
class FileChangeData:
    path: str
    change_type: ChangeType
    diff: str


class WorkspaceError(Exception):
    pass


class Workspace:
    """A scratch copy of the sample repo that one agent run works in.

    Tracks a snapshot of every file at creation time so diffs can be
    computed after the agent edits the copy. All paths are validated to
    stay inside the workspace root.
    """

    def __init__(self, root: Path, snapshot: dict[str, str]) -> None:
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
        ws = cls(root, {})
        ws._snapshot = {path: ws.read_file(path) for path in ws.list_files()}
        return ws

    def _resolve(self, rel_path: str) -> Path:
        resolved = (self.root / rel_path).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise WorkspaceError(f"Path escapes the workspace: {rel_path!r}")
        return resolved

    def list_files(self) -> list[str]:
        files = []
        for path in self.root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                files.append(path.relative_to(self.root).as_posix())
        return sorted(files)

    def read_file(self, rel_path: str) -> str:
        target = self._resolve(rel_path)
        if not target.is_file():
            raise WorkspaceError(f"File not found: {rel_path!r}")
        return target.read_text(errors="replace")

    def write_file(self, rel_path: str, content: str) -> None:
        target = self._resolve(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def delete_file(self, rel_path: str) -> None:
        target = self._resolve(rel_path)
        if not target.is_file():
            raise WorkspaceError(f"File not found: {rel_path!r}")
        target.unlink()

    def compute_changes(self) -> list[FileChangeData]:
        changes = []
        current_files = set(self.list_files())
        all_paths = sorted(current_files | set(self._snapshot))
        for path in all_paths:
            before = self._snapshot.get(path)
            after = self.read_file(path) if path in current_files else None
            if before == after:
                continue
            if before is None:
                change_type = ChangeType.create
            elif after is None:
                change_type = ChangeType.delete
            else:
                change_type = ChangeType.modify
            diff = "".join(
                difflib.unified_diff(
                    (before or "").splitlines(keepends=True),
                    (after or "").splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
            changes.append(FileChangeData(path=path, change_type=change_type, diff=diff))
        return changes

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
