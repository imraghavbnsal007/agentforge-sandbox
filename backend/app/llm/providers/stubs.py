"""Placeholder providers: registered and visible, not yet implemented.

Each raises a clear LLMProviderError when used, so selecting one fails a task
gracefully instead of crashing the worker.
"""

from app.core.config import settings
from app.llm.base import BaseLLMProvider
from app.llm.types import LLMProviderError, LLMResponse, Message


class _NotImplementedProvider(BaseLLMProvider):
    name = ""  # subclasses set; empty name is not registered

    def __init__(self) -> None:
        super().__init__()
        raise LLMProviderError(
            f"The {self.label} provider is not implemented yet — "
            "use 'anthropic' or 'google'."
        )

    @classmethod
    def is_configured(cls) -> bool:
        return False

    async def chat(
        self,
        model: str,
        messages: list[Message],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 16000,
        json_schema: dict | None = None,
    ) -> LLMResponse:  # pragma: no cover - constructor always raises
        raise LLMProviderError(f"{self.label} provider is not implemented yet")


class OpenAIProvider(_NotImplementedProvider):
    name = "openai"
    label = "OpenAI"
    known_models: list[str] = []

    @classmethod
    def is_configured(cls) -> bool:
        return bool(settings.openai_api_key)


class OpenRouterProvider(_NotImplementedProvider):
    name = "openrouter"
    label = "OpenRouter"
    known_models: list[str] = []

    @classmethod
    def is_configured(cls) -> bool:
        return bool(settings.openrouter_api_key)


class OllamaProvider(_NotImplementedProvider):
    name = "ollama"
    label = "Ollama (local)"
    known_models: list[str] = []

    @classmethod
    def is_configured(cls) -> bool:
        return bool(settings.ollama_url)
