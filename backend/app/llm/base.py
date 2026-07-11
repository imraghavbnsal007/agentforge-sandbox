"""BaseLLMProvider: the single interface every provider implements.

Providers subclass this and implement `chat()` plus metadata (name, models,
pricing, configuration check). The semantic operations — plan, summarize,
review, analyze_repository — are implemented here on top of chat(), so
prompts stay identical across providers and a new provider is exactly one
class: subclassing auto-registers it.
"""

import json
import re
from abc import ABC, abstractmethod

from app.llm.types import LLMProviderError, LLMResponse, Message, text_message

SYSTEM_PROMPT = (
    "You are AgentForge, an expert software engineer. You implement feature "
    "requests in a small repository. Write clean, idiomatic code that matches "
    "the existing style, and always cover new behavior with tests."
)

_REGISTRY: dict[str, type["BaseLLMProvider"]] = {}


def get_provider_class(name: str) -> type["BaseLLMProvider"]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise LLMProviderError(
            f"Unknown LLM provider {name!r}. Available: {sorted(_REGISTRY)}"
        ) from None


def all_providers() -> dict[str, type["BaseLLMProvider"]]:
    return dict(_REGISTRY)


class BaseLLMProvider(ABC):
    # Subclasses set these.
    name: str = ""
    label: str = ""
    # Model prefix -> (usd_per_mtok_in, usd_per_mtok_out). Approximate list prices.
    pricing: dict[str, tuple[float, float]] = {}
    # Models offered in the UI. The provider decides validity — anything the
    # upstream API accepts is allowed; this list is presentation only.
    known_models: list[str] = []
    # Rough output speed for latency estimates (tokens/second).
    output_tokens_per_second: float = 40.0

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name:
            _REGISTRY[cls.name] = cls

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    # -- Model ID normalization ---------------------------------------------
    #
    # Canonical internal model IDs are "provider/model" (e.g.
    # "google/gemini-2.5-flash"), matching how ModelSpec/LLMRun/the UI
    # display them. Providers must accept a bare model id too — callers
    # (env vars, DB rows written via raw API calls, profile overrides) are
    # not guaranteed to strip the prefix before it reaches here. Each
    # provider normalizes independently; the default strips its own
    # "<name>/" prefix if present and leaves anything else untouched.

    @classmethod
    def normalize_model_id(cls, model: str) -> str:
        prefix = f"{cls.name}/"
        if model.startswith(prefix):
            return model[len(prefix):]
        return model

    # -- Required per provider -------------------------------------------

    @classmethod
    @abstractmethod
    def is_configured(cls) -> bool:
        """Whether credentials/config for this provider are present."""

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[Message],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 16000,
    ) -> LLMResponse:
        """One model call in the neutral message format."""

    # -- Shared behavior ---------------------------------------------------

    def scrub(self, text: str) -> str:
        if self._api_key:
            text = text.replace(self._api_key, "***")
        return text

    def estimate_cost(
        self, model: str, tokens_in: int, tokens_out: int
    ) -> float | None:
        """USD estimate from the pricing table; None when the model is unknown."""
        best: tuple[float, float] | None = None
        best_len = -1
        for prefix, prices in self.pricing.items():
            if model.startswith(prefix) and len(prefix) > best_len:
                best, best_len = prices, len(prefix)
        if best is None:
            return None
        return round(tokens_in / 1e6 * best[0] + tokens_out / 1e6 * best[1], 6)

    def estimate_latency_seconds(self, tokens_out: int) -> float:
        return round(2.0 + tokens_out / self.output_tokens_per_second, 1)

    # -- Semantic operations (identical prompts for every provider) --------

    async def plan(
        self, model: str, title: str, request: str, repo_context: str
    ) -> tuple[list[str], LLMResponse]:
        prompt = (
            f"Feature request: {title}\n\n{request}\n\n"
            f"Repository contents:\n\n{repo_context}\n\n"
            "Write a short implementation plan for this request: 3 to 7 steps, "
            "one per line, each starting with a number. Output only the plan."
        )
        response = await self.chat(
            model,
            [text_message("user", prompt)],
            system=SYSTEM_PROMPT,
            max_tokens=2048,
        )
        steps = []
        for line in response.text.splitlines():
            step = line.strip().lstrip("0123456789.)- ").strip()
            if step:
                steps.append(step)
        if not steps:
            raise LLMProviderError(f"{self.label} returned an empty plan")
        return steps, response

    async def summarize(
        self, model: str, title: str, request: str, diffs: str, tests_summary: str
    ) -> tuple[str, LLMResponse]:
        prompt = (
            f"Feature request: {title}\n\n{request}\n\n"
            f"Diffs of the changes you made:\n\n{diffs}\n\n"
            f"Test results: {tests_summary}\n\n"
            "Write a PR-style summary in markdown: a short title heading, what "
            "changed and why, a bullet list of files changed, and a test "
            "results section. Be concise."
        )
        response = await self.chat(
            model,
            [text_message("user", prompt)],
            system=SYSTEM_PROMPT,
            max_tokens=2048,
        )
        return response.text.strip(), response

    async def review(
        self, model: str, diffs: str, context: str
    ) -> tuple[str, LLMResponse]:
        prompt = (
            f"Review the following changes.\n\nContext:\n{context}\n\n"
            f"Diffs:\n\n{diffs}\n\n"
            "List concrete issues (correctness, tests, style) as short bullet "
            "points, most severe first. If there are no issues, say so plainly."
        )
        response = await self.chat(
            model,
            [text_message("user", prompt)],
            system=SYSTEM_PROMPT,
            max_tokens=2048,
        )
        return response.text.strip(), response

    async def analyze_repository(
        self, model: str, prompt: str
    ) -> tuple[dict, LLMResponse]:
        """Repository-analysis call that must return a JSON object."""
        response = await self.chat(
            model, [text_message("user", prompt)], max_tokens=4096
        )
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.text.strip())
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"{self.label} returned unparseable analysis JSON"
            ) from exc
        if not isinstance(data, dict):
            raise LLMProviderError(f"{self.label} analysis JSON was not an object")
        return data, response
