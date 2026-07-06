from dataclasses import dataclass
from typing import Protocol

from app.core.enums import AgentMode, ChangeType


@dataclass
class FileChangeData:
    path: str
    change_type: ChangeType
    diff: str


@dataclass
class TestResultData:
    suite: str
    passed: int
    failed: int
    errored: int
    duration: float
    output: str


class AgentRunner(Protocol):
    """The agent 'brain'. Implementations: stub (mock mode) and, in Phase 2, Claude API."""

    mode: AgentMode

    async def generate_plan(self, title: str, request: str) -> list[str]: ...

    async def apply_changes(self, title: str, request: str) -> list[FileChangeData]: ...

    async def run_tests(self, title: str, request: str) -> TestResultData: ...

    async def summarize(
        self,
        title: str,
        request: str,
        plan: list[str],
        changes: list[FileChangeData],
        tests: TestResultData,
    ) -> str: ...


def get_runner(mode: AgentMode) -> AgentRunner:
    if mode == AgentMode.mock:
        from app.agent.stub_runner import StubAgentRunner

        return StubAgentRunner()
    raise NotImplementedError(
        "AGENT_MODE=llm (Claude API runner) arrives in Phase 2 — use AGENT_MODE=mock"
    )
