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

    # --- LLM provider configuration (all env-overridable, no code changes) ---
    llm_provider: str = "anthropic"
    default_model: str = ""  # empty -> falls back to anthropic_model below
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"  # legacy name, kept for env compat
    google_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_url: str = ""
    # Execution profile building blocks (models are configuration, not code).
    profile_cheap_provider: str = "google"
    profile_cheap_model: str = "gemini-2.5-flash"
    profile_balanced_provider: str = "anthropic"
    profile_balanced_model: str = "claude-sonnet-5"
    profile_premium_provider: str = "anthropic"
    profile_premium_model: str = "claude-opus-4-8"

    sample_repo_path: str = str(_REPO_ROOT / "sample_repo")

    def resolved_default_model(self) -> str:
        return self.default_model or self.anthropic_model
    github_token: str = ""
    # Optional comma-separated allowlist ("owner/repo,owner/repo2"). When set,
    # publishing to any repo not in the list fails even if a project row
    # is configured for it.
    github_allowed_repos: str = ""

    def allowed_repos(self) -> set[str] | None:
        if not self.github_allowed_repos.strip():
            return None
        return {r.strip() for r in self.github_allowed_repos.split(",") if r.strip()}
    # Seconds the mock runner pauses between pipeline steps so status
    # transitions are observable in the UI. Tests set this to 0.
    agent_step_delay: float = 1.5


settings = Settings()
