"""Google Gemini provider — the only module that imports the google-genai SDK."""

import asyncio
import re
import time
import uuid

from app.core.config import settings
from app.llm.base import BaseLLMProvider
from app.llm.types import LLMProviderError, LLMResponse, LLMToolCall, Message

# Free-tier RPM quotas reset per minute; a couple of paced retries let an
# agent loop finish instead of dying mid-run.
MAX_RATE_LIMIT_RETRIES = 2
DEFAULT_RETRY_DELAY_S = 30.0
MAX_RETRY_DELAY_S = 65.0


def _retry_delay_seconds(error_text: str) -> float:
    """Parse the server-suggested delay ('Please retry in 46.79s' /
    retryDelay: '46s'); fall back to a conservative default."""
    match = re.search(r"retry in ([\d.]+)\s*s", error_text, re.IGNORECASE)
    if not match:
        match = re.search(r"retryDelay[^\d]*([\d.]+)", error_text)
    if match:
        try:
            return min(float(match.group(1)) + 1.0, MAX_RETRY_DELAY_S)
        except ValueError:
            pass
    return DEFAULT_RETRY_DELAY_S


class GeminiProvider(BaseLLMProvider):
    name = "google"
    label = "Google Gemini"
    # gemini-2.5-flash is intentionally absent from the dropdown: it is
    # unavailable to new users. It stays in `pricing` so historical runs
    # keep displaying and estimating correctly.
    known_models = ["gemini-3.5-flash", "gemini-2.5-pro"]
    # Approximate list prices, USD per MTok (in, out).
    pricing = {
        "gemini-3.5-flash": (1.50, 9.00),
        "gemini-2.5-flash": (0.30, 2.50),
        "gemini-2.5-pro": (1.25, 10.0),
    }
    output_tokens_per_second = 90.0

    @classmethod
    def is_configured(cls) -> bool:
        import os

        return bool(settings.google_api_key or os.environ.get("GOOGLE_API_KEY"))

    @classmethod
    def normalize_model_id(cls, model: str) -> str:
        # Strip our own "google/" prefix, then the Developer API's discovery
        # prefix ("models/gemini-2.5-flash") in case one arrives already
        # partially normalized — generate_content wants the bare id either way.
        model = super().normalize_model_id(model)
        if model.startswith("models/"):
            model = model[len("models/"):]
        return model

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
            # Replay the model's own turn verbatim when we have it — thinking
            # models attach thought_signature to function-call parts and the
            # API rejects reconstructed parts that lack it.
            if message["role"] == "assistant" and message.get("raw") is not None:
                contents.append(message["raw"])
                continue
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

    async def _describe_available_models(self, limit: int = 8) -> str:
        """Best-effort model list for a readable 404 message.

        Tries the live API first; falls back to the cached known_models list
        (per-provider) if the list call itself fails for any reason.
        """
        names: list[str] = []
        try:
            async for entry in await self.client.aio.models.list(
                config={"page_size": 50, "query_base": True}
            ):
                supported = entry.supported_actions or []
                if supported and "generateContent" not in supported:
                    continue
                name = (entry.name or "").rsplit("/", 1)[-1]
                if name and name not in names:
                    names.append(name)
                if len(names) >= limit:
                    break
        except Exception:
            names = []
        if not names:
            names = list(self.known_models)[:limit]
        if not names:
            return "Could not retrieve the list of available models."
        return "Available text-generation models include: " + ", ".join(names)

    async def _raise_readable(
        self, code, detail: str, exc: Exception, model: str, original_model: str
    ) -> None:
        """Map a non-retryable APIError to a readable LLMProviderError."""
        if code in (401, 403):
            raise LLMProviderError(
                f"Google Gemini auth/permission error ({code}) — check GOOGLE_API_KEY"
            ) from exc
        if code == 404:
            available = await self._describe_available_models()
            configured = (
                f"{original_model!r} (normalized to {model!r})"
                if original_model != model
                else repr(model)
            )
            hint = ""
            if model.startswith("gemini-2.5-flash"):
                hint = (
                    " Gemini 2.5 Flash is unavailable for new users. "
                    "Use Gemini 3.5 Flash."
                )
            raise LLMProviderError(
                f"Google Gemini 404 — unknown model {configured}.{hint} {available}"
            ) from exc
        if code == 429:
            raise LLMProviderError(
                "Google Gemini rate limited (429) — retries exhausted; "
                "wait a minute and retry the task"
            ) from exc
        raise LLMProviderError(
            f"Google Gemini API error ({code}): {detail}"
        ) from exc

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

        original_model = model
        model = self.normalize_model_id(model)

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

        attempts = 0
        while True:
            start = time.monotonic()
            try:
                response = await self.client.aio.models.generate_content(
                    model=model,
                    contents=self._to_contents(messages),
                    config=types.GenerateContentConfig(**config_kwargs),
                )
                break
            except genai_errors.APIError as exc:
                code = getattr(exc, "code", "?")
                detail = self.scrub(str(getattr(exc, "message", exc)))
                if code == 429 and attempts < MAX_RATE_LIMIT_RETRIES:
                    # Free-tier RPM windows reset each minute; honor the
                    # server's suggested delay so agent loops can finish.
                    attempts += 1
                    await asyncio.sleep(_retry_delay_seconds(str(exc)))
                    continue
                await self._raise_readable(code, detail, exc, model, original_model)
            except LLMProviderError:
                raise
            except Exception as exc:  # network/transport errors vary by backend
                raise LLMProviderError(
                    self.scrub(
                        f"Could not reach the Google Gemini API: {type(exc).__name__}"
                    )
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
        raw_content = None
        if response.candidates:
            raw_content = response.candidates[0].content
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end",
            tokens_in=(usage.prompt_token_count or 0) if usage else 0,
            tokens_out=(usage.candidates_token_count or 0) if usage else 0,
            model=model,
            provider=self.name,
            latency_ms=latency_ms,
            raw=raw_content,
        )
