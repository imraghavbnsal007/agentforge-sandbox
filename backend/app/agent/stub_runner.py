import asyncio

from app.core.config import settings
from app.core.enums import AgentMode, ChangeType
from app.agent.runner import FileChangeData, TestResultData

STUB_DIFF = """\
--- a/sample_repo/calculator.py
+++ b/sample_repo/calculator.py
@@ -10,3 +10,7 @@
 def add(a, b):
     return a + b
+
+
+def multiply(a, b):
+    return a * b
"""


class StubAgentRunner:
    """Deterministic mock agent: canned plan, one fake diff, one fake test run.

    Pauses `delay` seconds between steps so the pending → planning → coding →
    testing → completed progression is visible while polling the API.
    """

    mode = AgentMode.mock

    def __init__(self, delay: float | None = None) -> None:
        self.delay = settings.agent_step_delay if delay is None else delay

    async def _pause(self) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)

    async def generate_plan(self, title: str, request: str) -> list[str]:
        await self._pause()
        return [
            "Analyze the feature request",
            "Locate the relevant module in the sample repo",
            "Implement the change",
            "Add unit tests",
            "Run the test suite",
        ]

    async def apply_changes(self, title: str, request: str) -> list[FileChangeData]:
        await self._pause()
        return [
            FileChangeData(
                path="sample_repo/calculator.py",
                change_type=ChangeType.modify,
                diff=STUB_DIFF,
            )
        ]

    async def run_tests(self, title: str, request: str) -> TestResultData:
        await self._pause()
        return TestResultData(
            suite="pytest",
            passed=12,
            failed=0,
            errored=0,
            duration=0.42,
            output="============ 12 passed in 0.42s ============",
        )

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
            f"Implemented the requested change (stub run — no real agent yet).\n\n"
            f"### Files changed\n{files}\n\n"
            f"### Tests\n{tests.passed} passed, {tests.failed} failed "
            f"in {tests.duration}s.\n"
        )
