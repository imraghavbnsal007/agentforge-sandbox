"""LLMRunner: the provider-agnostic tool-use loop (replaces ClaudeRunner tests)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm_runner import (
    MAX_EDIT_TURNS,
    MAX_SPINNING_TURNS,
    LLMRunner,
    _repo_context,
)
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


# -- when the agent does not finish by itself -------------------------------
#
# Running out of turns used to raise, which discarded every edit the run had
# made. It is not a failure: the workspace holds real work, and the run now
# carries a warning through to the diff, the tests and the pull request body.


async def test_a_finished_loop_reports_itself_complete(
    session: AsyncSession, workspace: Workspace
):
    runner, _ = make_runner(
        session,
        [tool_response(("list_files", {})), text_response("done")],
    )
    outcome = await runner.apply_changes("T", "R", ["s"], workspace, lambda _m: None)
    assert outcome.complete
    assert outcome.turns == 2


async def test_a_model_going_in_circles_is_stopped_early(
    session: AsyncSession, workspace: Workspace
):
    """Repeating the same call proves nothing is being learned or changed.

    Waiting for the turn ceiling would burn another seventy calls to reach
    the same conclusion, slowly and at the user's expense.
    """
    endless = [tool_response(("list_files", {})) for _ in range(MAX_EDIT_TURNS)]
    runner, provider = make_runner(session, endless)

    outcome = await runner.apply_changes("T", "R", ["s"], workspace, lambda _m: None)

    assert not outcome.complete
    assert "repeated the same tool call" in outcome.reason
    # First turn is novel, then MAX_SPINNING_TURNS repeats.
    assert outcome.turns == MAX_SPINNING_TURNS + 1
    assert len(provider.calls) == MAX_SPINNING_TURNS + 1


async def test_varied_work_is_never_mistaken_for_spinning(
    session: AsyncSession, workspace: Workspace
):
    """The stall detector must not cut short an agent doing real work."""
    responses = [
        tool_response(("write_file", {"path": f"f{i}.py", "content": f"# {i}\n"}))
        for i in range(MAX_SPINNING_TURNS + 3)
    ]
    responses.append(text_response("done"))
    runner, _ = make_runner(session, responses)

    outcome = await runner.apply_changes("T", "R", ["s"], workspace, lambda _m: None)

    assert outcome.complete
    assert (workspace.root / f"f{MAX_SPINNING_TURNS + 2}.py").exists()


async def test_a_repeat_after_real_work_does_not_count_toward_a_stall(
    session: AsyncSession, workspace: Workspace
):
    """Re-reading a file between edits is normal, not a loop."""
    read = tool_response(("read_file", {"path": "calculator.py"}))
    responses = [
        read,
        tool_response(("write_file", {"path": "a.py", "content": "# a\n"})),
        read,
        tool_response(("write_file", {"path": "b.py", "content": "# b\n"})),
        read,
        text_response("done"),
    ]
    runner, _ = make_runner(session, responses)

    outcome = await runner.apply_changes("T", "R", ["s"], workspace, lambda _m: None)
    assert outcome.complete


async def test_the_turn_ceiling_stops_rather_than_raises(
    session: AsyncSession, workspace: Workspace
):
    """A model that keeps doing genuinely new things still has a backstop."""
    responses = [
        tool_response(("write_file", {"path": f"f{i}.py", "content": f"# {i}\n"}))
        for i in range(MAX_EDIT_TURNS + 5)
    ]
    runner, _ = make_runner(session, responses)

    outcome = await runner.apply_changes("T", "R", ["s"], workspace, lambda _m: None)

    assert not outcome.complete
    assert f"{MAX_EDIT_TURNS}-turn limit" in outcome.reason
    assert outcome.turns == MAX_EDIT_TURNS


async def test_the_edits_made_before_stopping_survive(
    session: AsyncSession, workspace: Workspace
):
    """The whole point of not raising: the work is still there."""
    stuck = tool_response(("list_files", {}))
    responses = [
        tool_response(("write_file", {"path": "kept.py", "content": "# kept\n"})),
        stuck,
        stuck,
        stuck,
        stuck,
    ]
    runner, _ = make_runner(session, responses)

    outcome = await runner.apply_changes("T", "R", ["s"], workspace, lambda _m: None)

    assert not outcome.complete
    assert (workspace.root / "kept.py").read_text() == "# kept\n"
    assert "kept.py" in {c.path for c in workspace.compute_changes()}


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


async def test_gemini_fallback_mid_loop_causes_no_duplicate_edits(
    session: AsyncSession, workspace: Workspace
):
    """A 503 fallback re-issues only the failed chat call — the conversation
    (and every edit already made) is preserved, nothing is re-executed."""
    from app.llm.types import LLMUnavailableError

    provider = FakeProvider(
        [
            tool_response(
                ("write_file", {"path": "calculator.py",
                                "content": "def divide(a, b):\n    return a / b\n"}),
            ),
            LLMUnavailableError("Google Gemini unavailable (503)"),
            text_response("Done."),
        ]
    )
    provider.name = "google"
    service_module._instances["google"] = provider
    spec = ModelSpec("google", "gemini-3.5-flash")
    service = LLMService(session)
    runner = LLMRunner(
        service=service,
        specs={phase: spec for phase in
               ("planning", "coding", "review", "summarize", "analysis")},
    )
    logs: list[str] = []
    service.log = logs.append
    await runner.apply_changes("Add divide", "R", ["step"], workspace, logs.append)

    # The edit happened exactly once.
    assert workspace.read_file("calculator.py").count("def divide") == 1
    assert sum("write_file calculator.py" in line for line in logs) == 1
    # The fallback call replayed the same conversation, not a fresh task:
    # attempt 2 (failed, Flash) and attempt 3 (Flash Lite) got identical
    # messages, including the earlier tool result.
    assert provider.calls[1]["messages"] == provider.calls[2]["messages"]
    assert provider.calls[2]["model"] == "gemini-3.1-flash-lite"
    assert any("continued with Gemini 3.1 Flash Lite" in line for line in logs)

    # llm_runs shows what actually ran: Flash ok, Flash failed, Lite ok.
    runs = (await session.execute(select(LLMRun).order_by(LLMRun.id))).scalars().all()
    assert [(r.model, r.success) for r in runs] == [
        ("gemini-3.5-flash", True),
        ("gemini-3.5-flash", False),
        ("gemini-3.1-flash-lite", True),
    ]
