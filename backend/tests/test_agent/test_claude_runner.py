from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.claude_runner import ClaudeRunner
from app.agent.workspace import Workspace
from app.core.config import settings


@pytest.fixture
def workspace():
    ws = Workspace.create_from(settings.sample_repo_path)
    yield ws
    ws.cleanup()


def text_response(text: str):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


def tool_response(*calls):
    blocks = [
        SimpleNamespace(type="tool_use", id=f"tu_{i}", name=name, input=tool_input)
        for i, (name, tool_input) in enumerate(calls)
    ]
    return SimpleNamespace(stop_reason="tool_use", content=blocks)


def make_runner(responses):
    client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=responses))
    )
    return ClaudeRunner(client=client, model="claude-opus-4-8"), client


def test_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ClaudeRunner()


async def test_generate_plan_parses_numbered_lines(workspace: Workspace):
    runner, _ = make_runner(
        [text_response("1. Read the code\n2) Add the function\n3 - Add tests\n")]
    )
    plan = await runner.generate_plan("Add divide", "Add divide(a, b).", workspace)
    assert plan == ["Read the code", "Add the function", "Add tests"]


async def test_generate_plan_empty_raises(workspace: Workspace):
    runner, _ = make_runner([text_response("")])
    with pytest.raises(RuntimeError, match="empty plan"):
        await runner.generate_plan("T", "R", workspace)


async def test_apply_changes_tool_loop(workspace: Workspace):
    runner, client = make_runner(
        [
            tool_response(
                ("read_file", {"path": "calculator.py"}),
                ("write_file", {"path": "calculator.py", "content": "def divide(a, b):\n    return a / b\n"}),
            ),
            tool_response(
                ("write_file", {"path": "tests/test_divide.py", "content": "from calculator import divide\n"}),
            ),
            text_response("Done — divide implemented with tests."),
        ]
    )
    logs: list[str] = []
    await runner.apply_changes("Add divide", "Add divide.", ["step"], workspace, logs.append)

    assert "def divide" in workspace.read_file("calculator.py")
    assert "tests/test_divide.py" in workspace.list_files()
    assert client.messages.create.await_count == 3
    assert any("write_file calculator.py" in line for line in logs)
    # Tool results for parallel calls must go back in ONE user message.
    second_call_messages = client.messages.create.await_args_list[1].kwargs["messages"]
    tool_result_msg = second_call_messages[2]
    assert tool_result_msg["role"] == "user"
    assert len(tool_result_msg["content"]) == 2


async def test_apply_changes_tool_error_reported(workspace: Workspace):
    runner, client = make_runner(
        [
            tool_response(("read_file", {"path": "missing.py"})),
            text_response("Could not find the file; stopping."),
        ]
    )
    await runner.apply_changes("T", "R", ["step"], workspace, lambda _msg: None)
    messages = client.messages.create.await_args_list[1].kwargs["messages"]
    result = messages[2]["content"][0]
    assert result["is_error"] is True


async def test_apply_changes_iteration_cap(workspace: Workspace):
    endless = tool_response(("list_files", {}))
    runner, _ = make_runner([endless] * 25)
    with pytest.raises(RuntimeError, match="Edit loop exceeded"):
        await runner.apply_changes("T", "R", ["step"], workspace, lambda _msg: None)
