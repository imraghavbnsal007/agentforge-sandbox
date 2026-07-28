from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import AgentMode, AuthMode

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
    profile_cheap_model: str = "gemini-3.1-flash-lite"
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

    # "development" or "production". Production enables strict startup
    # checks that reject cookie/CORS defaults which are fine locally.
    app_env: str = "development"

    # --- Authentication (Phase 6A) ----------------------------------------
    # local      -> no sign-in; every request resolves to the default local
    #               user, preserving the single-user PAT workflow.
    # github_app -> GitHub sign-in required; unauthenticated callers get 401.
    auth_mode: AuthMode = AuthMode.local

    # GitHub App OAuth credentials — used only to identify the user. They are
    # never used to clone, push, or open pull requests (that is the
    # installation token's job, added in Phase 6B).
    github_app_client_id: str = ""
    github_app_client_secret: str = ""
    # The App's URL slug, used to build the installation link
    # (https://github.com/apps/<slug>/installations/new).
    github_app_name: str = ""
    # Numeric App ID from the GitHub App settings page — the JWT issuer.
    github_app_id: str = ""
    # Path to the App's RSA private key. Mounted secret in production, a
    # gitignored file in development. The contents are never stored in the
    # database and never logged.
    github_app_private_key_path: str = ""
    # Re-mint an installation token this many seconds before GitHub expires
    # it, so a long clone/push cannot straddle the boundary.
    installation_token_refresh_margin_seconds: int = 300

    # Shared secret configured on the GitHub App's webhook. Deliveries are
    # rejected unless their HMAC matches; with no secret set, the endpoint
    # refuses everything rather than trusting unverifiable payloads.
    github_app_webhook_secret: str = ""
    # Failed-signature attempts tolerated per client per window. Valid
    # deliveries are never counted, so a genuine GitHub burst is not throttled.
    webhook_rate_limit_requests: int = 60
    webhook_rate_limit_window_seconds: int = 60

    # Commit identity used when publishing through a GitHub App installation.
    # Both are REQUIRED in github_app mode and deliberately have no default:
    # inventing a noreply address would attribute commits to an identity that
    # may not exist. Validated before the first App commit.
    github_app_commit_name: str = ""
    github_app_commit_email: str = ""
    # AUTH_MODE=local keeps the original identity.
    local_commit_name: str = "AgentForge"
    local_commit_email: str = "agentforge@localhost"
    # Where GitHub sends the user back after authorization. Must match the
    # GitHub App's "Callback URL" exactly.
    github_app_callback_url: str = "http://localhost:8000/api/v1/auth/github/callback"
    # Where the backend sends the browser once a session exists.
    frontend_url: str = "http://localhost:3000"

    session_cookie_name: str = "agentforge_session"
    csrf_cookie_name: str = "agentforge_csrf"
    # Secure=true requires HTTPS; keep false for local http:// development.
    cookie_secure: bool = False
    session_ttl_seconds: int = 7 * 24 * 3600

    # Comma-separated browser origins allowed to send credentialed requests.
    # A wildcard is rejected at startup: "*" plus credentials is never valid.
    cors_origins: str = "http://localhost:3000"

    # Trust X-Forwarded-For for the client IP. Enable only when running
    # behind a reverse proxy that overwrites the header.
    trust_proxy_headers: bool = False
    # Fixed-window rate limits for the sign-in routes.
    auth_rate_limit_requests: int = 10
    auth_rate_limit_window_seconds: int = 300

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def is_github_app_mode(self) -> bool:
        return self.auth_mode == AuthMode.github_app

    def github_oauth_configured(self) -> bool:
        return bool(self.github_app_client_id and self.github_app_client_secret)

    def github_app_configured(self) -> bool:
        """Whether installation tokens can be minted at all."""
        return bool(self.github_app_id and self.github_app_private_key_path)

    def webhooks_configured(self) -> bool:
        return bool(self.github_app_webhook_secret)

    def missing_commit_identity_settings(self) -> list[str]:
        """Which commit-identity settings are unset. Empty means usable."""
        missing = []
        if not self.github_app_commit_name.strip():
            missing.append("GITHUB_APP_COMMIT_NAME")
        if not self.github_app_commit_email.strip():
            missing.append("GITHUB_APP_COMMIT_EMAIL")
        return missing


settings = Settings()
