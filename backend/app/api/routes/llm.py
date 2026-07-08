"""Provider/model/profile options for the task UI, with cost estimates."""

from fastapi import APIRouter
from pydantic import BaseModel

import app.llm.providers  # noqa: F401  (registers providers)
from app.core.config import settings
from app.llm.base import all_providers
from app.llm.profiles import TASK_PHASES, estimate_profile, get_profiles

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


class ProviderInfo(BaseModel):
    name: str
    label: str
    configured: bool
    implemented: bool
    models: list[str]


class ProfileInfo(BaseModel):
    name: str
    phases: dict[str, str]
    estimated_cost_usd: float | None
    estimated_latency_seconds: float


class LLMOptions(BaseModel):
    default_provider: str
    default_model: str
    providers: list[ProviderInfo]
    profiles: list[ProfileInfo]


@router.get("/options", response_model=LLMOptions)
async def llm_options() -> LLMOptions:
    providers = []
    for name, cls in sorted(all_providers().items()):
        providers.append(
            ProviderInfo(
                name=name,
                label=cls.label,
                configured=cls.is_configured(),
                implemented=bool(cls.known_models),
                models=cls.known_models,
            )
        )
    profiles = []
    for name, specs in get_profiles().items():
        estimate = estimate_profile(specs, TASK_PHASES)
        profiles.append(
            ProfileInfo(
                name=name,
                phases={
                    phase: f"{spec.provider}/{spec.model}"
                    for phase, spec in specs.items()
                },
                estimated_cost_usd=estimate["estimated_cost_usd"],
                estimated_latency_seconds=estimate["estimated_latency_seconds"],
            )
        )
    return LLMOptions(
        default_provider=settings.llm_provider,
        default_model=settings.resolved_default_model(),
        providers=providers,
        profiles=profiles,
    )
