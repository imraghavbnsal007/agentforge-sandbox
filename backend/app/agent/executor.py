import asyncio
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Protocol

from app.agent.workspace import Workspace

TEST_TIMEOUT_SECONDS = 300


@dataclass
class TestResultData:
    __test__ = False  # not a pytest test class, despite the name

    suite: str
    passed: int
    failed: int
    errored: int
    duration: float
    output: str
    stderr: str


class TestExecutor(Protocol):
    async def run_tests(self, workspace: Workspace) -> TestResultData: ...


def _count(pattern: str, text: str) -> int:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else 0


class CommandExecutor:
    """Runs an arbitrary test command (e.g. a project's detected one) in the
    workspace and parses pass/fail counts from common runner output."""

    def __init__(self, command: str) -> None:
        self.command = command

    async def run_tests(self, workspace: Workspace) -> TestResultData:
        start = time.monotonic()
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                self.command,
                shell=True,
                cwd=workspace.root,
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT_SECONDS,
            )
            stdout, stderr = proc.stdout, proc.stderr
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = f"test command timed out after {TEST_TIMEOUT_SECONDS}s"
            returncode = -1
        duration = time.monotonic() - start

        # NUL bytes (e.g. from a test runner cat-ing a binary) are rejected
        # by PostgreSQL text columns.
        stdout = (stdout or "").replace("\x00", "")
        stderr = (stderr or "").replace("\x00", "")
        combined = stdout + "\n" + stderr
        passed = _count(r"(\d+) passed", combined) or _count(r"(\d+) passing", combined)
        failed = _count(r"(\d+) failed", combined) or _count(r"(\d+) failing", combined)
        errored = _count(r"(\d+) error", combined)
        # A failing exit code with unparseable output must not look green.
        if returncode != 0 and failed == 0 and errored == 0:
            errored = 1

        return TestResultData(
            suite=self.command,
            passed=passed,
            failed=failed,
            errored=errored,
            duration=round(duration, 2),
            output=stdout,
            stderr=stderr,
        )


class PytestExecutor(CommandExecutor):
    """Default executor for the sample repo and unanalyzed projects."""

    def __init__(self) -> None:
        super().__init__(
            f"{sys.executable} -m pytest -q --tb=short -p no:cacheprovider"
        )
        # Keep the historical suite label.
        self.suite_label = "pytest"

    async def run_tests(self, workspace: Workspace) -> TestResultData:
        result = await super().run_tests(workspace)
        result.suite = "pytest"
        return result
