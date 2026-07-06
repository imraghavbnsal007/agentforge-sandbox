import asyncio
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Protocol

from app.agent.workspace import Workspace

PYTEST_TIMEOUT_SECONDS = 120


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


class PytestExecutor:
    """Runs pytest inside the workspace and parses the summary line."""

    async def run_tests(self, workspace: Workspace) -> TestResultData:
        start = time.monotonic()
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"],
                cwd=workspace.root,
                capture_output=True,
                text=True,
                timeout=PYTEST_TIMEOUT_SECONDS,
            )
            stdout, stderr = proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = f"pytest timed out after {PYTEST_TIMEOUT_SECONDS}s"
        duration = time.monotonic() - start

        return TestResultData(
            suite="pytest",
            passed=_count(r"(\d+) passed", stdout),
            failed=_count(r"(\d+) failed", stdout),
            errored=_count(r"(\d+) error", stdout),
            duration=round(duration, 2),
            output=stdout,
            stderr=stderr,
        )
