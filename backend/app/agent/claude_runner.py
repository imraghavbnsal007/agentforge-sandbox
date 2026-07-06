"""The real AI engineer: Claude editing the workspace through a tool-use loop."""

import anthropic

from app.agent.executor import TestResultData
from app.agent.runner import LogFn
from app.agent.workspace import FileChangeData, Workspace, WorkspaceError
from app.core.config import settings
from app.core.enums import AgentMode

MAX_EDIT_ITERATIONS = 20
MAX_TOKENS = 16000
# Repo is tiny; guard against pathological content in prompts anyway.
MAX_CONTEXT_CHARS = 60_000

SYSTEM_PROMPT = (
    "You are AgentForge, an expert software engineer. You implement feature "
    "requests in a small Python repository. Write clean, idiomatic Python that "
    "matches the existing style, and always cover new behavior with pytest tests."
)

EDIT_TOOLS = [
    {
        "name": "list_files",
        "description": "List every file in the repository (relative paths).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Read the full contents of a file in the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a file in the repository with the given "
            "content. Always write the complete file content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"},
                "content": {"type": "string", "description": "Full file content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file from the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"}
            },
            "required": ["path"],
        },
    },
]


def _repo_context(workspace: Workspace) -> str:
    parts = []
    total = 0
    for path in workspace.list_files():
        content = workspace.read_file(path)
        total += len(content)
        if total > MAX_CONTEXT_CHARS:
            parts.append(f"### {path}\n(omitted — context limit reached)")
            continue
        parts.append(f"### {path}\n```\n{content}\n```")
    return "\n\n".join(parts)


class ClaudeRunner:
    """Plans, edits, and summarizes using the Claude API.

    The edit phase is an agentic tool-use loop: Claude reads and writes
    workspace files through tools until it decides the change is complete.
    """

    mode = AgentMode.llm

    def __init__(
        self,
        client: anthropic.AsyncAnthropic | None = None,
        model: str | None = None,
    ) -> None:
        if client is None:
            if not settings.anthropic_api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set — required for AGENT_MODE=llm"
                )
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.client = client
        self.model = model or settings.anthropic_model

    async def generate_plan(
        self, title: str, request: str, workspace: Workspace
    ) -> list[str]:
        prompt = (
            f"Feature request: {title}\n\n{request}\n\n"
            f"Repository contents:\n\n{_repo_context(workspace)}\n\n"
            "Write a short implementation plan for this request: 3 to 7 steps, "
            "one per line, each starting with a number. Output only the plan."
        )
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        steps = []
        for line in text.splitlines():
            step = line.strip().lstrip("0123456789.)- ").strip()
            if step:
                steps.append(step)
        if not steps:
            raise RuntimeError("Claude returned an empty plan")
        return steps

    async def apply_changes(
        self,
        title: str,
        request: str,
        plan: list[str],
        workspace: Workspace,
        log: LogFn,
    ) -> None:
        plan_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(plan))
        messages: list[dict] = [
            {
                "role": "user",
                "content": (
                    f"Feature request: {title}\n\n{request}\n\n"
                    f"Your implementation plan:\n{plan_text}\n\n"
                    f"Repository contents:\n\n{_repo_context(workspace)}\n\n"
                    "Implement the plan by editing the repository with the "
                    "provided tools. Include pytest tests for new behavior. "
                    "When the implementation is complete, stop calling tools "
                    "and reply with a one-line confirmation."
                ),
            }
        ]

        for _ in range(MAX_EDIT_ITERATIONS):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=EDIT_TOOLS,
                messages=messages,
            )
            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content if b.type == "text")
                log(f"claude: {text.strip() or 'finished editing'}")
                return

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result, is_error = self._run_tool(block.name, block.input, workspace, log)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        raise RuntimeError(f"Edit loop exceeded {MAX_EDIT_ITERATIONS} iterations")

    def _run_tool(
        self, name: str, tool_input: dict, workspace: Workspace, log: LogFn
    ) -> tuple[str, bool]:
        try:
            if name == "list_files":
                log("claude: list_files")
                return "\n".join(workspace.list_files()), False
            path = tool_input.get("path", "")
            if name == "read_file":
                log(f"claude: read_file {path}")
                return workspace.read_file(path), False
            if name == "write_file":
                log(f"claude: write_file {path}")
                workspace.write_file(path, tool_input.get("content", ""))
                return f"Wrote {path}", False
            if name == "delete_file":
                log(f"claude: delete_file {path}")
                workspace.delete_file(path)
                return f"Deleted {path}", False
            return f"Unknown tool: {name}", True
        except WorkspaceError as exc:
            log(f"claude: tool error — {exc}")
            return str(exc), True

    async def summarize(
        self,
        title: str,
        request: str,
        plan: list[str],
        changes: list[FileChangeData],
        tests: TestResultData,
    ) -> str:
        diffs = "\n\n".join(f"```diff\n{c.diff}\n```" for c in changes) or "(none)"
        prompt = (
            f"Feature request: {title}\n\n{request}\n\n"
            f"Diffs of the changes you made:\n\n{diffs}\n\n"
            f"Test results: {tests.passed} passed, {tests.failed} failed, "
            f"{tests.errored} errored in {tests.duration}s.\n"
            f"Test output:\n```\n{tests.output[-3000:]}\n```\n\n"
            "Write a PR-style summary in markdown: a short title heading, what "
            "changed and why, a bullet list of files changed, and a test "
            "results section. Be concise."
        )
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()
