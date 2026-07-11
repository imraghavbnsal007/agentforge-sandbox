"""LLMRunner: the provider-agnostic tool-use loop (replaces ClaudeRunner tests)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm_runner import LLMRunner, _repo_context
from app.agent.workspace import Workspace
from app.core.config import settings
from app.llm import service as service_module
from app.llm.profiles import ModelSpec
from app.llm.service import LLMService
from app.llm.types import LLMProviderError
from app.models import LLMRun
from tests.test_llm.fakes import FakeProvider, text_response, tool_response


@pytest.fixture(autouse=True)
def _fresh_provider_cache():
    service_module.reset_provider_cache()
    yield
    service_module.reset_provider_cache()


@pytest.fixture
def workspace():
    ws = Workspace.create_from(settings.sample_repo_path)
    yield ws
    ws.cleanup()


def make_runner(session: AsyncSession, responses, project_id=None) -> tuple[LLMRunner, FakeProvider]:
    provider = FakeProvider(responses)
    provider.name = "anthropic"
    service_module._instances["anthropic"] = provider
    spec = ModelSpec("anthropic", "claude-sonnet-5")
    runner = LLMRunner(
        service=LLMService(session, project_id=project_id),
        specs={phase: spec for phase in ("planning", "coding", "review", "summarize", "analysis")},
    )
    return runner, provider


async def test_generate_plan(session: AsyncSession, workspace: Workspace):
    runner, _ = make_runner(session, [text_response("1. One\n2. Two")])
    plan = await runner.generate_plan("T", "R", workspace)
    assert plan == ["One", "Two"]
    # The call was tracked.
    runs = (await session.execute(select(LLMRun))).scalars().all()
    assert runs[0].phase == "planning"


async def test_apply_changes_tool_loop(session: AsyncSession, workspace: Workspace):
    runner, provider = make_runner(
        session,
        [
            tool_response(
                ("read_file", {"path": "calculator.py"}),
                ("write_file", {"path": "calculator.py",
                                "content": "def divide(a, b):\n    return a / b\n"}),
            ),
            tool_response(
                ("write_file", {"path": "tests/test_divide.py",
                                "content": "from calculator import divide\n"}),
            ),
            text_response("Done."),
        ],
    )
    logs: list[str] = []
    await runner.apply_changes("Add divide", "Add divide.", ["step"], workspace, logs.append)

    assert "def divide" in workspace.read_file("calculator.py")
    assert "tests/test_divide.py" in workspace.list_files()
    assert len(provider.calls) == 3
    # Parallel tool results return in ONE user message.
    second_call = provider.calls[1]["messages"]
    assert second_call[-1]["role"] == "user"
    assert len(second_call[-1]["content"]) == 2
    assert any("write_file calculator.py" in line for line in logs)
    # Three coding-phase LLMRuns recorded.
    runs = (await session.execute(select(LLMRun))).scalars().all()
    assert [r.phase for r in runs] == ["coding", "coding", "coding"]


async def test_runner_carries_raw_model_turn_for_replay(
    session: AsyncSession, workspace: Workspace
):
    """The assistant message must carry the provider's raw turn so providers
    that need verbatim replay (Gemini thought signatures) can use it."""
    first = tool_response(("list_files", {}))
    first.raw = {"sentinel": "raw-model-turn"}
    runner, provider = make_runner(session, [first, text_response("done")])
    await runner.apply_changes("T", "R", ["s"], workspace, lambda _m: None)

    second_call_messages = provider.calls[1]["messages"]
    assistant = second_call_messages[1]
    assert assistant["role"] == "assistant"
    assert assistant["raw"] == {"sentinel": "raw-model-turn"}


async def test_tool_error_reported_to_model(session: AsyncSession, workspace: Workspace):
    runner, provider = make_runner(
        session,
        [tool_response(("read_file", {"path": "missing.py"})), text_response("ok")],
    )
    await runner.apply_changes("T", "R", ["s"], workspace, lambda _m: None)
    result_block = provider.calls[1]["messages"][-1]["content"][0]
    assert result_block["is_error"] is True


async def test_iteration_cap(session: AsyncSession, workspace: Workspace):
    endless = [tool_response(("list_files", {})) for _ in range(25)]
    runner, _ = make_runner(session, endless)
    with pytest.raises(LLMProviderError, match="Edit loop exceeded"):
        await runner.apply_changes("T", "R", ["s"], workspace, lambda _m: None)


async def test_summarize_includes_binary_note(session: AsyncSession, workspace: Workspace):
    from app.agent.executor import TestResultData
    from app.agent.workspace import FileChangeData
    from app.core.enums import ChangeType

    runner, provider = make_runner(session, [text_response("## Summary")])
    changes = [
        FileChangeData(path="a.py", change_type=ChangeType.modify, diff="--- a\n+++ b\n"),
        FileChangeData(path="x.zip", change_type=ChangeType.delete, diff="",
                       is_binary=True, size_bytes=10, content_hash="h"),
    ]
    tests = TestResultData("pytest", 5, 0, 0, 0.1, "5 passed", "")
    text = await runner.summarize("T", "R", ["s"], changes, tests)
    assert text == "## Summary"
    prompt = provider.calls[0]["messages"][0]["content"][0]["text"]
    assert "(binary change: delete x.zip)" in prompt
    assert "PK" not in prompt  # binary bytes never reach the prompt


def test_repo_context_omits_binary(tmp_path):
    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "img.png").write_bytes(b"\x89PNG\x00\x00")
    ws = Workspace.from_dir(tmp_path)
    context = _repo_context(ws)
    assert "binary file — content omitted" in context
    assert "\x00" not in context
