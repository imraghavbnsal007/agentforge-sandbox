from typing import Callable, Protocol

from app.agent.executor import TestResultData
from app.agent.workspace import FileChangeData, Workspace
from app.core.enums import AgentMode

# Callback the runner uses to append lines to the run's execution log.
LogFn = Callable[[str], None]


class AgentRunner(Protocol):
    """The agent 'brain'. MockRunner is deterministic; ClaudeRunner calls the Claude API.

    Both operate on a Workspace (a scratch copy of the sample repo): they edit
    files in place, and RunService computes diffs and runs tests afterwards.
    """

    mode: AgentMode

    async def generate_plan(
        self, title: str, request: str, workspace: Workspace
    ) -> list[str]: ...

    async def apply_changes(
        self,
        title: str,
        request: str,
        plan: list[str],
        workspace: Workspace,
        log: LogFn,
    ) -> None: ...

    async def summarize(
        self,
        title: str,
        request: str,
        plan: list[str],
        changes: list[FileChangeData],
        tests: TestResultData,
    ) -> str: ...


# NOTE: runner construction for llm mode lives in RunService (it needs the
# task's provider/model/profile resolution and a DB session for LLMRun
# tracking); mock mode stays here.
def get_mock_runner() -> AgentRunner:
    from app.agent.mock_runner import MockRunner

    return MockRunner()
