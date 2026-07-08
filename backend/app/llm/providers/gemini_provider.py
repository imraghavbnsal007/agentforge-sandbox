"""Google Gemini provider — the only module that imports the google-genai SDK."""

import time
import uuid

from app.core.config import settings
from app.llm.base import BaseLLMProvider
from app.llm.types import LLMProviderError, LLMResponse, LLMToolCall, Message


class GeminiProvider(BaseLLMProvider):
    name = "google"
    label = "Google Gemini"
    known_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
    # Approximate list prices, USD per MTok (in, out).
    pricing = {
        "gemini-2.5-flash": (0.30, 2.50),
        "gemini-2.5-pro": (1.25, 10.0),
    }
    output_tokens_per_second = 90.0

    @classmethod
    def is_configured(cls) -> bool:
        import os

        return bool(settings.google_api_key or os.environ.get("GOOGLE_API_KEY"))

    def __init__(self, client=None) -> None:
        super().__init__(api_key=settings.google_api_key)
        if client is None:
            if not self.is_configured():
                raise LLMProviderError(
                    "GOOGLE_API_KEY is not set — required for the Google Gemini "
                    "provider. Add it to .env and restart."
                )
            try:
                from google import genai
            except ImportError as exc:
                raise LLMProviderError(
                    "The google-genai package is not installed in the backend image"
                ) from exc
            client = genai.Client(api_key=settings.google_api_key or None)
        self.client = client

    def _to_contents(self, messages: list[Message]):
        from google.genai import types

        contents = []
        for message in messages:
            role = "user" if message["role"] == "user" else "model"
            parts = []
            tool_results = []
            for block in message["content"]:
                if block["type"] == "text":
                    if block["text"]:
                        parts.append(types.Part.from_text(text=block["text"]))
                elif block["type"] == "tool_call":
                    parts.append(
                        types.Part.from_function_call(
                            name=block["name"], args=block["input"]
                        )
                    )
                elif block["type"] == "tool_result":
                    payload = (
                        {"error": block["content"]}
                        if block.get("is_error")
                        else {"result": block["content"]}
                    )
                    tool_results.append(
                        types.Part.from_function_response(
                            name=block["name"], response=payload
                        )
                    )
            if tool_results:
                contents.append(types.Content(role="tool", parts=tool_results))
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        return contents

    async def chat(
        self,
        model: str,
        messages: list[Message],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 16000,
    ) -> LLMResponse:
        from google.genai import errors as genai_errors
        from google.genai import types

        config_kwargs: dict = {"max_output_tokens": max_tokens}
        if system:
            config_kwargs["system_instruction"] = system
        if tools:
            declarations = [
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters_json_schema=t["input_schema"],
                )
                for t in tools
            ]
            config_kwargs["tools"] = [
                types.Tool(function_declarations=declarations)
            ]

        start = time.monotonic()
        try:
            response = await self.client.aio.models.generate_content(
                model=model,
                contents=self._to_contents(messages),
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except genai_errors.APIError as exc:
            code = getattr(exc, "code", "?")
            detail = self.scrub(str(getattr(exc, "message", exc)))
            if code in (401, 403):
                raise LLMProviderError(
                    f"Google Gemini auth/permission error ({code}) — check GOOGLE_API_KEY"
                ) from exc
            if code == 404:
                raise LLMProviderError(
                    f"Google Gemini 404 — unknown model {model!r}?"
                ) from exc
            if code == 429:
                raise LLMProviderError(
                    "Google Gemini rate limited (429) — wait a moment and retry"
                ) from exc
            raise LLMProviderError(
                f"Google Gemini API error ({code}): {detail}"
            ) from exc
        except Exception as exc:  # network/transport errors vary by backend
            raise LLMProviderError(
                self.scrub(f"Could not reach the Google Gemini API: {type(exc).__name__}")
            ) from exc
        latency_ms = int((time.monotonic() - start) * 1000)

        text = response.text or ""
        tool_calls = [
            LLMToolCall(
                id=getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:12]}",
                name=fc.name,
                input=dict(fc.args or {}),
            )
            for fc in (response.function_calls or [])
        ]
        usage = response.usage_metadata
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end",
            tokens_in=(usage.prompt_token_count or 0) if usage else 0,
            tokens_out=(usage.candidates_token_count or 0) if usage else 0,
            model=model,
            provider=self.name,
            latency_ms=latency_ms,
        )
