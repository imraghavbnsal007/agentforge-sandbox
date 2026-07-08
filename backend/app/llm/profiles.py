"""Execution profiles: which provider/model handles each pipeline phase.

Profiles are built from settings so every model name is configuration.
Cost/latency estimates use rough per-phase token heuristics — they are
order-of-magnitude guidance shown before execution, not billing.
"""

from dataclasses import dataclass

from app.core.config import settings
from app.llm.base import get_provider_class

PHASES = ("analysis", "planning", "coding", "review", "summarize")

# Rough (tokens_in, tokens_out) per phase for estimation only.
PHASE_TOKEN_ESTIMATES = {
    "analysis": (12_000, 2_500),
    "planning": (6_000, 800),
    "coding": (25_000, 6_000),
    "review": (8_000, 1_500),
    "summarize": (5_000, 800),
}
# Phases a normal task run executes (analysis runs separately).
TASK_PHASES = ("planning", "coding", "summarize")


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str


def get_profiles() -> dict[str, dict[str, ModelSpec]]:
    cheap = ModelSpec(settings.profile_cheap_provider, settings.profile_cheap_model)
    balanced = ModelSpec(
        settings.profile_balanced_provider, settings.profile_balanced_model
    )
    premium = ModelSpec(
        settings.profile_premium_provider, settings.profile_premium_model
    )
    return {
        "cheap": {phase: cheap for phase in PHASES},
        "balanced": {
            "analysis": cheap,
            "planning": balanced,
            "coding": balanced,
            "review": balanced,
            "summarize": balanced,
        },
        "premium": {phase: premium for phase in PHASES},
    }


def resolve_specs(
    task_provider: str | None,
    task_model: str | None,
    task_profile: str | None,
    project_provider: str | None = None,
    project_model: str | None = None,
    project_profile: str | None = None,
) -> dict[str, ModelSpec]:
    """Task overrides beat project preferences beat global defaults.

    An explicit provider+model pair means 'custom': every phase uses it.
    Otherwise the chosen profile decides per phase.
    """
    if task_provider and task_model:
        spec = ModelSpec(task_provider, task_model)
        return {phase: spec for phase in PHASES}
    profiles = get_profiles()
    if task_profile in profiles:
        return profiles[task_profile]
    if project_provider and project_model:
        spec = ModelSpec(project_provider, project_model)
        return {phase: spec for phase in PHASES}
    if project_profile in profiles:
        return profiles[project_profile]
    if settings.llm_provider and settings.default_model:
        spec = ModelSpec(settings.llm_provider, settings.default_model)
        return {phase: spec for phase in PHASES}
    return profiles["balanced"]


def estimate_profile(
    specs: dict[str, ModelSpec], phases: tuple[str, ...] = TASK_PHASES
) -> dict:
    """Expected cost (USD) and latency (s) for running the given phases."""
    total_cost = 0.0
    cost_known = True
    total_latency = 0.0
    for phase in phases:
        spec = specs[phase]
        tokens_in, tokens_out = PHASE_TOKEN_ESTIMATES[phase]
        provider_cls = get_provider_class(spec.provider)
        # estimate_cost/latency don't need credentials — call unbound-style.
        dummy = object.__new__(provider_cls)
        dummy._api_key = ""
        cost = provider_cls.estimate_cost(dummy, spec.model, tokens_in, tokens_out)
        if cost is None:
            cost_known = False
        else:
            total_cost += cost
        total_latency += provider_cls.estimate_latency_seconds(dummy, tokens_out)
    return {
        "estimated_cost_usd": round(total_cost, 4) if cost_known else None,
        "estimated_latency_seconds": round(total_latency, 1),
    }
