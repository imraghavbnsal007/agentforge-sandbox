from dataclasses import dataclass
from typing import Callable, Protocol

from app.agent.executor import TestResultData
from app.agent.workspace import FileChangeData, Workspace
from app.core.enums import AgentMode

# Callback the runner uses to append lines to the run's execution log.
LogFn = Callable[[str], None]


@dataclass(frozen=True)
class EditOutcome:
    """How the edit loop ended.

    `complete` is False when the agent ran out of turns or started going in
    circles. That is deliberately **not** a failure: the workspace still
    holds everything it did manage, and throwing that away — which is what
    raising used to do — was worse than handing it over with a warning
    attached. The run continues to diff, test and summarise as normal.
    """

    complete: bool
    reason: str = ""
    turns: int = 0

    @classmethod
    def finished(cls, turns: int = 0) -> "EditOutcome":
        return cls(complete=True, turns=turns)

    @classmethod
    def stopped(cls, reason: str, turns: int) -> "EditOutcome":
        return cls(complete=False, reason=reason, turns=turns)


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
    ) -> EditOutcome: ...

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
