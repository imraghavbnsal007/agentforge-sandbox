"""LLMService: the single gateway between AgentForge and providers.

Every call resolves a provider from the registry, executes it, and records
an LLMRun row (provider, model, tokens, cost, latency, success) — including
failures, so the Usage page reflects reality. Provider SDKs are never touched
outside app/llm/providers/*.
"""

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

import app.llm.providers  # noqa: F401  (registers all providers)
from app.llm.base import BaseLLMProvider, get_provider_class
from app.llm.profiles import ModelSpec
from app.llm.types import LLMProviderError, LLMResponse, Message
from app.models import LLMRun

logger = logging.getLogger(__name__)

_instances: dict[str, BaseLLMProvider] = {}


def get_provider(name: str) -> BaseLLMProvider:
    """Instantiate (and cache) a provider. Raises LLMProviderError with a
    readable message when unknown, unconfigured, or unimplemented."""
    if name not in _instances:
        _instances[name] = get_provider_class(name)()
    return _instances[name]


def reset_provider_cache() -> None:
    _instances.clear()


class LLMService:
    def __init__(
        self,
        session: AsyncSession,
        project_id: int | None = None,
        agent_run_id: int | None = None,
        analysis_id: int | None = None,
    ) -> None:
        self.session = session
        self.project_id = project_id
        self.agent_run_id = agent_run_id
        self.analysis_id = analysis_id

    async def _record(
        self,
        spec: ModelSpec,
        phase: str,
        response: LLMResponse | None,
        error: str | None,
        latency_ms: int,
    ) -> None:
        # Record the model actually invoked, not necessarily the "provider/model"
        # form the caller configured — a stray prefix must not silently zero
        # out cost estimation (pricing tables key on the bare model id).
        cost = None
        recorded_model = response.model if response is not None else spec.model
        try:
            provider_cls = get_provider_class(spec.provider)
            if response is None:
                recorded_model = provider_cls.normalize_model_id(spec.model)
            else:
                dummy = object.__new__(provider_cls)
                dummy._api_key = ""
                cost = provider_cls.estimate_cost(
                    dummy, recorded_model, response.tokens_in, response.tokens_out
                )
        except LLMProviderError:
            # Unknown provider: still record the run, cost unknown.
            pass
        self.session.add(
            LLMRun(
                project_id=self.project_id,
                agent_run_id=self.agent_run_id,
                analysis_id=self.analysis_id,
                provider=spec.provider,
                model=recorded_model,
                phase=phase,
                tokens_in=response.tokens_in if response else 0,
                tokens_out=response.tokens_out if response else 0,
                estimated_cost=cost,
                latency_ms=response.latency_ms if response else latency_ms,
                success=error is None,
                error_message=error,
            )
        )
        await self.session.commit()

    async def _run(self, spec: ModelSpec, phase: str, operation) -> tuple:
        """Execute `operation(provider)` and record the LLMRun either way."""
        start = time.monotonic()
        try:
            provider = get_provider(spec.provider)
            result, response = await operation(provider)
        except LLMProviderError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            await self._record(spec, phase, None, str(exc), latency_ms)
            raise
        await self._record(spec, phase, response, None, response.latency_ms)
        return result, response

    # -- Public surface (mirrors BaseLLMProvider semantics) -----------------

    async def chat(
        self,
        spec: ModelSpec,
        phase: str,
        messages: list[Message],
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 16000,
    ) -> LLMResponse:
        async def op(provider: BaseLLMProvider):
            response = await provider.chat(
                spec.model, messages, system=system, tools=tools, max_tokens=max_tokens
            )
            return response, response

        _, response = await self._run(spec, phase, op)
        return response

    async def plan(
        self, spec: ModelSpec, title: str, request: str, repo_context: str
    ) -> list[str]:
        async def op(provider: BaseLLMProvider):
            return await provider.plan(spec.model, title, request, repo_context)

        steps, _ = await self._run(spec, "planning", op)
        return steps

    async def summarize(
        self, spec: ModelSpec, title: str, request: str, diffs: str, tests_summary: str
    ) -> str:
        async def op(provider: BaseLLMProvider):
            return await provider.summarize(
                spec.model, title, request, diffs, tests_summary
            )

        text, _ = await self._run(spec, "summarize", op)
        return text

    async def review(self, spec: ModelSpec, diffs: str, context: str) -> str:
        async def op(provider: BaseLLMProvider):
            return await provider.review(spec.model, diffs, context)

        text, _ = await self._run(spec, "review", op)
        return text

    async def analyze_repository(self, spec: ModelSpec, prompt: str) -> dict:
        async def op(provider: BaseLLMProvider):
            return await provider.analyze_repository(spec.model, prompt)

        data, _ = await self._run(spec, "analysis", op)
        return data
