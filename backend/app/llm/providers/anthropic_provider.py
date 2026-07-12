"""Anthropic provider — the only module in AgentForge that imports the
anthropic SDK."""

import time

import anthropic

from app.core.config import settings
from app.llm.base import BaseLLMProvider
from app.llm.types import LLMProviderError, LLMResponse, LLMToolCall, Message


def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
    converted = []
    for message in messages:
        blocks = []
        for block in message["content"]:
            if block["type"] == "text":
                blocks.append({"type": "text", "text": block["text"]})
            elif block["type"] == "tool_call":
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": block["id"],
                        "name": block["name"],
                        "input": block["input"],
                    }
                )
            elif block["type"] == "tool_result":
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["tool_call_id"],
                        "content": block["content"],
                        "is_error": block.get("is_error", False),
                    }
                )
        converted.append({"role": message["role"], "content": blocks})
    return converted


class AnthropicProvider(BaseLLMProvider):
    name = "anthropic"
    label = "Anthropic"
    known_models = ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"]
    # Approximate list prices, USD per MTok (in, out).
    pricing = {
        "claude-fable-5": (10.0, 50.0),
        "claude-opus": (5.0, 25.0),
        "claude-sonnet": (3.0, 15.0),
        "claude-haiku": (1.0, 5.0),
    }
    output_tokens_per_second = 45.0

    @classmethod
    def is_configured(cls) -> bool:
        import os

        return bool(
            settings.anthropic_api_key
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        super().__init__(api_key=settings.anthropic_api_key)
        if client is None:
            client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key or None
            )
            if not client.api_key and not client.auth_token:
                raise LLMProviderError(
                    "ANTHROPIC_API_KEY is not set — required for the Anthropic "
                    "provider. Add it to .env and restart."
                )
        self.client = client

    async def chat(
        self,
        model: str,
        messages: list[Message],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 16000,
        json_schema: dict | None = None,
    ) -> LLMResponse:
        # json_schema is accepted for interface parity but intentionally
        # unused: Anthropic has no equivalent server-side JSON mode here, so
        # callers parse the text response defensively instead.
        model = self.normalize_model_id(model)
        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        start = time.monotonic()
        try:
            response = await self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMProviderError(
                "Anthropic authentication failed (401) — check ANTHROPIC_API_KEY"
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMProviderError(
                f"Anthropic permission denied (403) — the API key lacks access "
                f"to model {model!r}"
            ) from exc
        except anthropic.NotFoundError as exc:
            raise LLMProviderError(
                f"Anthropic 404 — unknown model {model!r}?"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LLMProviderError(
                "Anthropic rate limited (429) — wait a moment and retry"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise LLMProviderError(
                self.scrub(f"Anthropic API error ({exc.status_code}): {exc.message}")
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMProviderError(
                "Could not reach the Anthropic API — check network connectivity"
            ) from exc
        except TypeError as exc:
            raise LLMProviderError(
                "Anthropic credentials missing or invalid — set ANTHROPIC_API_KEY"
            ) from exc
        latency_ms = int((time.monotonic() - start) * 1000)

        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    LLMToolCall(id=block.id, name=block.name, input=dict(block.input))
                )
        stop = {"tool_use": "tool_use", "max_tokens": "max_tokens"}.get(
            response.stop_reason, "end"
        )
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=stop,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            model=model,
            provider=self.name,
            latency_ms=latency_ms,
        )
