from fastapi import APIRouter
from pydantic import BaseModel

import app.llm.providers  # noqa: F401  (registers providers)
from app.core.config import settings
from app.core.enums import AgentMode, AuthMode
from app.llm.base import all_providers

router = APIRouter(prefix="/api/v1", tags=["meta"])


class ConfigRead(BaseModel):
    agent_mode: AgentMode
    auth_mode: AuthMode
    llm_provider: str
    default_model: str
    # Kept for backward compatibility with older UI reads.
    anthropic_model: str
    api_key_configured: bool
    github_token_configured: bool
    providers_configured: dict[str, bool]


@router.get("/config", response_model=ConfigRead)
async def get_config() -> ConfigRead:
    return ConfigRead(
        agent_mode=settings.agent_mode,
        auth_mode=settings.auth_mode,
        llm_provider=settings.llm_provider,
        default_model=settings.resolved_default_model(),
        anthropic_model=settings.resolved_default_model(),
        api_key_configured=bool(settings.anthropic_api_key),
        github_token_configured=bool(settings.github_token),
        providers_configured={
            name: cls.is_configured() for name, cls in all_providers().items()
        },
    )
