"""Configuration validation run at startup.

Catches a misconfigured deployment at boot rather than at the first user
request. Two rules govern everything here:

  * AUTH_MODE=local must never require GitHub App configuration — the
    single-user workflow has to keep working with nothing but a PAT;
  * a problem names the *setting*, never its value. Secrets are never
    read into a message, and the private key is checked for readability
    without its contents being touched.
"""

import logging
from dataclasses import dataclass, field

from app.core.config import settings

logger = logging.getLogger(__name__)

PRODUCTION = "production"


@dataclass
class ConfigurationReport:
    """Problems found, split by whether they block startup."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = []
        if self.errors:
            lines.append("Configuration errors:")
            lines += [f"  - {problem}" for problem in self.errors]
        if self.warnings:
            lines.append("Configuration warnings:")
            lines += [f"  - {problem}" for problem in self.warnings]
        return "\n".join(lines)


class ConfigurationError(RuntimeError):
    """Startup refused. The message names settings, never their values."""


# GitHub App settings required before github_app mode can function, mapped to
# why each is needed.
_GITHUB_APP_REQUIREMENTS = [
    ("github_app_client_id", "GITHUB_APP_CLIENT_ID", "GitHub sign-in"),
    ("github_app_client_secret", "GITHUB_APP_CLIENT_SECRET", "GitHub sign-in"),
    ("github_app_id", "GITHUB_APP_ID", "minting installation tokens"),
    (
        "github_app_private_key_path",
        "GITHUB_APP_PRIVATE_KEY_PATH",
        "minting installation tokens",
    ),
    (
        "github_app_webhook_secret",
        "GITHUB_APP_WEBHOOK_SECRET",
        "verifying webhook deliveries",
    ),
    (
        "github_app_commit_name",
        "GITHUB_APP_COMMIT_NAME",
        "attributing commits",
    ),
    (
        "github_app_commit_email",
        "GITHUB_APP_COMMIT_EMAIL",
        "attributing commits",
    ),
]


def _check_infrastructure(report: ConfigurationReport) -> None:
    if not settings.database_url.strip():
        report.errors.append("DATABASE_URL is not set")
    if not settings.redis_url.strip():
        report.errors.append(
            "REDIS_URL is not set — required for sessions, OAuth state and "
            "installation-token caching"
        )


def _check_github_app(report: ConfigurationReport) -> None:
    for attribute, env_name, purpose in _GITHUB_APP_REQUIREMENTS:
        if not str(getattr(settings, attribute, "") or "").strip():
            report.errors.append(f"{env_name} is not set — required for {purpose}")

    # Readability only. The contents are never read into a message or log.
    path_value = settings.github_app_private_key_path.strip()
    if path_value:
        from pathlib import Path

        path = Path(path_value)
        try:
            with path.open("rb") as handle:
                handle.read(1)
        except OSError as exc:
            report.errors.append(
                f"GITHUB_APP_PRIVATE_KEY_PATH points at {path_value!r}, which "
                f"is not readable ({type(exc).__name__}). Check the file and "
                "the container mount."
            )

    if not settings.github_app_name.strip():
        report.warnings.append(
            "GITHUB_APP_NAME is not set — the 'Install GitHub App' link cannot "
            "be built, so users cannot reach the installation page"
        )


def _check_production_hardening(report: ConfigurationReport) -> None:
    """Reject defaults that are fine locally but unsafe on a public host."""
    if not settings.cookie_secure:
        report.errors.append(
            "COOKIE_SECURE must be true in production — session cookies would "
            "otherwise be sent over plain HTTP"
        )
    if not settings.frontend_url.lower().startswith("https://"):
        report.errors.append(
            "FRONTEND_URL must be https:// in production"
        )
    if not settings.github_app_callback_url.lower().startswith("https://"):
        report.errors.append(
            "GITHUB_APP_CALLBACK_URL must be https:// in production"
        )
    insecure_origins = [
        origin
        for origin in settings.cors_origin_list()
        if not origin.lower().startswith("https://")
    ]
    if insecure_origins:
        report.errors.append(
            "CORS_ORIGINS must contain only https:// origins in production "
            f"({len(insecure_origins)} plain-http origin(s) configured)"
        )


def check_configuration() -> ConfigurationReport:
    """Inspect settings and report problems. Never raises."""
    report = ConfigurationReport()
    _check_infrastructure(report)

    if settings.is_github_app_mode():
        _check_github_app(report)
    else:
        # Local mode: GitHub App settings are irrelevant by design.
        if not settings.github_token.strip():
            report.warnings.append(
                "GITHUB_TOKEN is not set — repository operations will fail "
                "until it is, though the app will start"
            )

    if settings.app_env.strip().lower() == PRODUCTION:
        _check_production_hardening(report)

    return report


def enforce_configuration() -> ConfigurationReport:
    """Validate at startup, refusing to boot on an error.

    Warnings are logged and allowed through: they describe a degraded but
    functioning deployment, not a broken one.
    """
    report = check_configuration()
    for warning in report.warnings:
        logger.warning("Configuration warning: %s", warning)
    if not report.ok:
        raise ConfigurationError(
            "AgentForge cannot start with the current configuration.\n"
            + report.render()
        )
    logger.info(
        "Configuration validated (auth_mode=%s, env=%s)",
        settings.auth_mode,
        settings.app_env,
    )
    return report
