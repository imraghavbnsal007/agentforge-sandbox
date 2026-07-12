"""A scriptable in-memory provider for service/runner tests."""

from app.llm.base import BaseLLMProvider
from app.llm.types import LLMProviderError, LLMResponse, Message


class FakeProvider(BaseLLMProvider):
    name = ""  # not registered by default; tests seed the instance cache
    label = "Fake"
    pricing = {"fake-model": (1.0, 2.0)}
    known_models = ["fake-model"]

    def __init__(self, responses: list | None = None) -> None:
        super().__init__(api_key="")
        self.responses = list(responses or [])
        self.calls: list[dict] = []

    @classmethod
    def is_configured(cls) -> bool:
        return True

    async def chat(
        self,
        model: str,
        messages: list[Message],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 16000,
        json_schema: dict | None = None,
    ) -> LLMResponse:
        import copy

        # Deep-copy: the runner mutates its messages list across iterations.
        self.calls.append(
            {
                "model": model,
                "messages": copy.deepcopy(messages),
                "system": system,
                "tools": tools,
                "json_schema": json_schema,
            }
        )
        if not self.responses:
            raise LLMProviderError("FakeProvider ran out of scripted responses")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        item.model = item.model or model
        item.provider = item.provider or "fake"
        return item


def text_response(text: str, tokens_in: int = 100, tokens_out: int = 50) -> LLMResponse:
    return LLMResponse(
        text=text, stop_reason="end", tokens_in=tokens_in, tokens_out=tokens_out,
        latency_ms=5,
    )


def tool_response(*calls) -> LLMResponse:
    from app.llm.types import LLMToolCall

    return LLMResponse(
        text="",
        tool_calls=[
            LLMToolCall(id=f"tc_{i}", name=name, input=tool_input)
            for i, (name, tool_input) in enumerate(calls)
        ],
        stop_reason="tool_use",
        tokens_in=100,
        tokens_out=30,
        latency_ms=5,
    )
