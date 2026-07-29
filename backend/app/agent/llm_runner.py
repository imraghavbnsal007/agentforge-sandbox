"""The real AI engineer, provider-agnostic: any registered LLM provider
edits the workspace through the neutral tool-use loop. No provider SDK is
imported here — everything goes through LLMService."""

import json

from app.agent.executor import TestResultData
from app.agent.runner import EditOutcome, LogFn
from app.agent.workspace import FileChangeData, Workspace, WorkspaceError
from app.core.enums import AgentMode
from app.llm.profiles import ModelSpec
from app.llm.service import LLMService
from app.llm.types import Message, text_message

#: Hard ceiling, to stop a genuine runaway — a backstop, not a work budget.
#: The old limit of 20 looked like a budget but was really a cap on
#: *operations*, because a model that emits one tool call per turn gets one
#: edit per turn while a model that batches gets ten. Same nominal number,
#: an order of magnitude apart in what it buys. Spinning is now detected
#: directly, so this only has to be high enough not to bind on real work.
MAX_EDIT_TURNS = 80

#: Consecutive turns in which every call repeats one already made, argument
#: for argument. Such a turn changed nothing and learned nothing. Two in a
#: row is a model finding its footing; this many is a loop, and waiting for
#: the turn ceiling would burn another seventy turns to reach the same
#: conclusion — slowly, and at the user's expense.
MAX_SPINNING_TURNS = 3

MAX_TOKENS = 16000
# Repo is tiny; guard against pathological content in prompts anyway.
MAX_CONTEXT_CHARS = 60_000

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
        "description": "Delete a single file from the repository.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "delete_path",
        "description": (
            "Delete a file, an entire directory, or everything matching a "
            "glob pattern — in one call. Always prefer this over repeated "
            "delete_file calls when clearing generated files, caches or IDE "
            "directories. Examples: '.idea', '.gradle', 'db.sqlite3', "
            "'**/__pycache__', '**/*.pyc'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Relative path, directory, or glob pattern. "
                        "'**' matches across directories."
                    ),
                }
            },
            "required": ["pattern"],
        },
    },
]

#: Deleting a build cache can remove hundreds of files. The model needs to
#: know it worked, not to read every path back — and a full listing would eat
#: the context window the run still has editing to do with.
DELETION_REPORT_LIMIT = 20


def _describe_deletions(pattern: str, deleted: list[str]) -> str:
    listing = "\n".join(deleted[:DELETION_REPORT_LIMIT])
    if len(deleted) > DELETION_REPORT_LIMIT:
        listing += f"\n… and {len(deleted) - DELETION_REPORT_LIMIT} more"
    return f"Deleted {len(deleted)} file(s) matching {pattern!r}:\n{listing}"

SYSTEM_PROMPT = (
    "You are AgentForge, an expert software engineer. You implement feature "
    "requests in a small repository. Write clean, idiomatic code that matches "
    "the existing style, and always cover new behavior with tests. "
    "Batch your work: use delete_path with a glob to remove groups of files "
    "in one call, and make as many tool calls per turn as the change needs. "
    "You have a limited number of turns, not a limited number of edits."
)


def _call_signature(call) -> str:
    """Identity of a tool call: same name and same arguments, same effect.

    Content is part of it on purpose — writing a file the same way twice is
    genuinely a repeat, and that is the shape most edit loops go round in.
    """
    return f"{call.name}:{json.dumps(call.input, sort_keys=True, default=str)}"


def _repo_context(workspace: Workspace) -> str:
    parts = []
    total = 0
    for path in workspace.list_files():
        try:
            content = workspace.read_file(path)
        except WorkspaceError:
            parts.append(f"### {path}\n(binary file — content omitted)")
            continue
        total += len(content)
        if total > MAX_CONTEXT_CHARS:
            parts.append(f"### {path}\n(omitted — context limit reached)")
            continue
        parts.append(f"### {path}\n```\n{content}\n```")
    return "\n\n".join(parts)


class LLMRunner:
    """Plans, edits, and summarizes using the configured providers per phase."""

    mode = AgentMode.llm

    def __init__(self, service: LLMService, specs: dict[str, ModelSpec]) -> None:
        self.service = service
        self.specs = specs

    async def generate_plan(
        self, title: str, request: str, workspace: Workspace
    ) -> list[str]:
        return await self.service.plan(
            self.specs["planning"], title, request, _repo_context(workspace)
        )

    async def apply_changes(
        self,
        title: str,
        request: str,
        plan: list[str],
        workspace: Workspace,
        log: LogFn,
    ) -> EditOutcome:
        spec = self.specs["coding"]
        plan_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(plan))
        messages: list[Message] = [
            text_message(
                "user",
                f"Feature request: {title}\n\n{request}\n\n"
                f"Your implementation plan:\n{plan_text}\n\n"
                f"Repository contents:\n\n{_repo_context(workspace)}\n\n"
                "Implement the plan by editing the repository with the "
                "provided tools. Include tests for new behavior. "
                "When the implementation is complete, stop calling tools "
                "and reply with a one-line confirmation.",
            )
        ]

        seen_calls: set[str] = set()
        spinning = 0
        turns = 0

        for turns in range(1, MAX_EDIT_TURNS + 1):
            response = await self.service.chat(
                spec,
                "coding",
                messages,
                system=SYSTEM_PROMPT,
                tools=EDIT_TOOLS,
                max_tokens=MAX_TOKENS,
            )
            if response.stop_reason != "tool_use" or not response.tool_calls:
                log(f"agent: {response.text.strip() or 'finished editing'}")
                return EditOutcome.finished(turns)

            assistant_blocks: list[dict] = []
            if response.text:
                assistant_blocks.append({"type": "text", "text": response.text})
            for call in response.tool_calls:
                assistant_blocks.append(
                    {
                        "type": "tool_call",
                        "id": call.id,
                        "name": call.name,
                        "input": call.input,
                    }
                )
            assistant_message: dict = {"role": "assistant", "content": assistant_blocks}
            if response.raw is not None:
                # Lets the provider replay its own turn verbatim (required by
                # Gemini thinking models' thought signatures).
                assistant_message["raw"] = response.raw
            messages.append(assistant_message)

            result_blocks = []
            for call in response.tool_calls:
                result, is_error = self._run_tool(call.name, call.input, workspace, log)
                result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": result,
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": result_blocks})

            signatures = [_call_signature(call) for call in response.tool_calls]
            if all(signature in seen_calls for signature in signatures):
                spinning += 1
                if spinning >= MAX_SPINNING_TURNS:
                    return self._stop(
                        log,
                        turns,
                        f"the model repeated the same tool call(s) for "
                        f"{spinning} turns running without changing anything",
                    )
            else:
                spinning = 0
            seen_calls.update(signatures)

        return self._stop(
            log, turns, f"the {MAX_EDIT_TURNS}-turn limit was reached"
        )

    @staticmethod
    def _stop(log: LogFn, turns: int, why: str) -> EditOutcome:
        reason = (
            f"The agent stopped after {turns} turns because {why}. "
            "The changes it did make are included below and may be incomplete."
        )
        log(f"agent: stopping — {why}")
        return EditOutcome.stopped(reason, turns)

    def _run_tool(
        self, name: str, tool_input: dict, workspace: Workspace, log: LogFn
    ) -> tuple[str, bool]:
        try:
            if name == "list_files":
                log("agent: list_files")
                return "\n".join(workspace.list_files()), False
            path = tool_input.get("path", "")
            if name == "read_file":
                log(f"agent: read_file {path}")
                return workspace.read_file(path), False
            if name == "write_file":
                log(f"agent: write_file {path}")
                workspace.write_file(path, tool_input.get("content", ""))
                return f"Wrote {path}", False
            if name == "delete_file":
                log(f"agent: delete_file {path}")
                workspace.delete_file(path)
                return f"Deleted {path}", False
            if name == "delete_path":
                pattern = tool_input.get("pattern", "")
                deleted = workspace.delete_path(pattern)
                log(f"agent: delete_path {pattern} — {len(deleted)} file(s)")
                return _describe_deletions(pattern, deleted), False
            return f"Unknown tool: {name}", True
        except WorkspaceError as exc:
            log(f"agent: tool error — {exc}")
            return str(exc), True

    async def summarize(
        self,
        title: str,
        request: str,
        plan: list[str],
        changes: list[FileChangeData],
        tests: TestResultData,
    ) -> str:
        diffs = (
            "\n\n".join(
                f"```diff\n{c.diff}\n```"
                if not c.is_binary
                else f"(binary change: {c.change_type} {c.path})"
                for c in changes
            )
            or "(none)"
        )
        tests_summary = (
            f"{tests.passed} passed, {tests.failed} failed, "
            f"{tests.errored} errored in {tests.duration}s "
            f"(suite: {tests.suite})\nOutput:\n{tests.output[-3000:]}"
        )
        return await self.service.summarize(
            self.specs["summarize"], title, request, diffs, tests_summary
        )
