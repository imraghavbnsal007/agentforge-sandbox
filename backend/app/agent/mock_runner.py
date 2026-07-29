import asyncio

from app.agent.executor import TestResultData
from app.agent.runner import EditOutcome, LogFn
from app.agent.workspace import FileChangeData, Workspace
from app.core.config import settings
from app.core.enums import AgentMode

MULTIPLY_FUNCTION = '''

def multiply(a, b):
    return a * b
'''

MULTIPLY_TESTS = '''from calculator import multiply


def test_multiply():
    assert multiply(3, 4) == 12


def test_multiply_by_zero():
    assert multiply(5, 0) == 0
'''


class MockRunner:
    """Deterministic agent: makes a real, fixed edit to the workspace.

    Adds multiply() to calculator.py plus a test file, so the whole pipeline
    (workspace copy, diff computation, real pytest run) is exercised without
    any API calls. Pauses `delay` seconds between steps so status transitions
    are visible while polling.
    """

    mode = AgentMode.mock

    def __init__(self, delay: float | None = None) -> None:
        self.delay = settings.agent_step_delay if delay is None else delay

    async def _pause(self) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)

    async def generate_plan(
        self, title: str, request: str, workspace: Workspace
    ) -> list[str]:
        await self._pause()
        return [
            "Review the feature request and the sample repo layout",
            "Add a multiply(a, b) function to calculator.py",
            "Add unit tests covering the new function",
            "Run the test suite to verify the change",
        ]

    async def apply_changes(
        self,
        title: str,
        request: str,
        plan: list[str],
        workspace: Workspace,
        log: LogFn,
    ) -> EditOutcome:
        await self._pause()
        calculator = workspace.read_file("calculator.py")
        workspace.write_file("calculator.py", calculator + MULTIPLY_FUNCTION)
        log("mock: appended multiply() to calculator.py")
        workspace.write_file("tests/test_multiply.py", MULTIPLY_TESTS)
        log("mock: created tests/test_multiply.py")
        return EditOutcome.finished()

    async def summarize(
        self,
        title: str,
        request: str,
        plan: list[str],
        changes: list[FileChangeData],
        tests: TestResultData,
    ) -> str:
        await self._pause()
        files = "\n".join(f"- `{c.path}` ({c.change_type})" for c in changes)
        return (
            f"## {title}\n\n"
            f"Implemented the requested change using the deterministic mock agent "
            f"(set `AGENT_MODE=llm` for the real Claude agent).\n\n"
            f"### Files changed\n{files}\n\n"
            f"### Tests\n{tests.passed} passed, {tests.failed} failed, "
            f"{tests.errored} errored in {tests.duration}s.\n"
        )
