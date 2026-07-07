from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.core.enums import AgentMode

router = APIRouter(prefix="/api/v1", tags=["meta"])


class ConfigRead(BaseModel):
    agent_mode: AgentMode
    anthropic_model: str
    api_key_configured: bool


@router.get("/config", response_model=ConfigRead)
async def get_config() -> ConfigRead:
    return ConfigRead(
        agent_mode=settings.agent_mode,
        anthropic_model=settings.anthropic_model,
        api_key_configured=bool(settings.anthropic_api_key),
    )
