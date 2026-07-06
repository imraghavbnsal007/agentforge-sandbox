from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import AgentMode

# Repo root when running outside Docker (backend/app/core/config.py -> repo root)
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://agentforge:agentforge@localhost:5432/agentforge"
    redis_url: str = "redis://localhost:6379/0"
    agent_mode: AgentMode = AgentMode.mock
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    sample_repo_path: str = str(_REPO_ROOT / "sample_repo")
    # Seconds the mock runner pauses between pipeline steps so status
    # transitions are observable in the UI. Tests set this to 0.
    agent_step_delay: float = 1.5


settings = Settings()
