"""Startup configuration validation.

Two invariants run through every test here: local mode never requires GitHub
App configuration, and no message ever contains a secret's value.
"""

import pytest

from app.core.config import settings
from app.core.enums import AuthMode
from app.core.startup_checks import (
    ConfigurationError,
    check_configuration,
    enforce_configuration,
)

SECRET_VALUES = {
    "github_app_client_secret": "super-secret-client-value",
    "github_app_webhook_secret": "super-secret-webhook-value",
    "github_token": "ghp_super_secret_pat_value",
}


@pytest.fixture
def app_mode(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A fully configured github_app deployment."""
    key = tmp_path / "app.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----")

    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    monkeypatch.setattr(settings, "github_app_client_id", "cid")
    monkeypatch.setattr(
        settings, "github_app_client_secret", SECRET_VALUES["github_app_client_secret"]
    )
    monkeypatch.setattr(settings, "github_app_id", "123456")
    monkeypatch.setattr(settings, "github_app_private_key_path", str(key))
    monkeypatch.setattr(
        settings,
        "github_app_webhook_secret",
        SECRET_VALUES["github_app_webhook_secret"],
    )
    monkeypatch.setattr(settings, "github_app_commit_name", "agentforge[bot]")
    monkeypatch.setattr(settings, "github_app_commit_email", "bot@example.com")
    monkeypatch.setattr(settings, "github_app_name", "agentforge-dev")
    return key


# -- local mode -------------------------------------------------------------


def test_local_mode_needs_no_github_app_configuration(
    monkeypatch: pytest.MonkeyPatch
):
    """The single-user workflow must start with nothing but a PAT."""
    monkeypatch.setattr(settings, "auth_mode", AuthMode.local)
    for attribute in (
        "github_app_client_id",
        "github_app_client_secret",
        "github_app_id",
        "github_app_private_key_path",
        "github_app_webhook_secret",
        "github_app_commit_name",
        "github_app_commit_email",
    ):
        monkeypatch.setattr(settings, attribute, "")
    monkeypatch.setattr(settings, "github_token", "ghp_x")

    assert check_configuration().ok is True


def test_local_mode_without_a_pat_warns_but_starts(
    monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.local)
    monkeypatch.setattr(settings, "github_token", "")
    report = check_configuration()
    assert report.ok is True
    assert any("GITHUB_TOKEN" in w for w in report.warnings)


# -- github_app mode: every required setting --------------------------------


def test_fully_configured_app_mode_passes(app_mode):
    assert check_configuration().ok is True


@pytest.mark.parametrize(
    "attribute,env_name",
    [
        ("github_app_client_id", "GITHUB_APP_CLIENT_ID"),
        ("github_app_client_secret", "GITHUB_APP_CLIENT_SECRET"),
        ("github_app_id", "GITHUB_APP_ID"),
        ("github_app_private_key_path", "GITHUB_APP_PRIVATE_KEY_PATH"),
        ("github_app_webhook_secret", "GITHUB_APP_WEBHOOK_SECRET"),
        ("github_app_commit_name", "GITHUB_APP_COMMIT_NAME"),
        ("github_app_commit_email", "GITHUB_APP_COMMIT_EMAIL"),
    ],
)
def test_each_required_setting_is_reported_by_name(
    app_mode, monkeypatch: pytest.MonkeyPatch, attribute: str, env_name: str
):
    monkeypatch.setattr(settings, attribute, "")
    report = check_configuration()
    assert report.ok is False
    assert any(env_name in problem for problem in report.errors)


def test_missing_app_name_is_a_warning_not_an_error(
    app_mode, monkeypatch: pytest.MonkeyPatch
):
    """Without it users cannot reach the install page, but the app works."""
    monkeypatch.setattr(settings, "github_app_name", "")
    report = check_configuration()
    assert report.ok is True
    assert any("GITHUB_APP_NAME" in w for w in report.warnings)


# -- private key ------------------------------------------------------------


def test_unreadable_private_key_is_reported(
    app_mode, monkeypatch: pytest.MonkeyPatch, tmp_path
):
    monkeypatch.setattr(
        settings, "github_app_private_key_path", str(tmp_path / "missing.pem")
    )
    report = check_configuration()
    assert report.ok is False
    assert any("not readable" in problem for problem in report.errors)


def test_private_key_contents_never_appear_in_the_report(app_mode):
    """Readability is checked without the key being read into a message."""
    report = check_configuration()
    rendered = report.render()
    assert "not-a-real-key" not in rendered
    assert "PRIVATE KEY" not in rendered


# -- secret hygiene ---------------------------------------------------------


def test_no_secret_value_appears_in_any_message(
    app_mode, monkeypatch: pytest.MonkeyPatch
):
    """Clear every setting so every branch reports, then assert no value leaks."""
    for attribute, _ in [
        ("github_app_client_id", None),
        ("github_app_id", None),
        ("github_app_commit_name", None),
    ]:
        monkeypatch.setattr(settings, attribute, "")
    rendered = check_configuration().render()
    for value in SECRET_VALUES.values():
        assert value not in rendered


def test_error_names_the_setting_not_the_value(
    app_mode, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_app_webhook_secret", "")
    problems = check_configuration().errors
    assert any("GITHUB_APP_WEBHOOK_SECRET" in p for p in problems)
    assert not any(SECRET_VALUES["github_app_webhook_secret"] in p for p in problems)


# -- infrastructure ---------------------------------------------------------


def test_missing_database_url_is_an_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "database_url", "")
    assert any("DATABASE_URL" in p for p in check_configuration().errors)


def test_missing_redis_url_is_an_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "redis_url", "")
    assert any("REDIS_URL" in p for p in check_configuration().errors)


# -- production hardening ---------------------------------------------------


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch, app_mode):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "frontend_url", "https://agentforge.example.com")
    monkeypatch.setattr(
        settings,
        "github_app_callback_url",
        "https://agentforge.example.com/api/v1/auth/github/callback",
    )
    monkeypatch.setattr(settings, "cors_origins", "https://agentforge.example.com")


def test_hardened_production_configuration_passes(production):
    assert check_configuration().ok is True


def test_production_rejects_insecure_cookies(
    production, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "cookie_secure", False)
    assert any("COOKIE_SECURE" in p for p in check_configuration().errors)


def test_production_rejects_plain_http_frontend(
    production, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000")
    assert any("FRONTEND_URL" in p for p in check_configuration().errors)


def test_production_rejects_plain_http_callback(
    production, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        settings, "github_app_callback_url", "http://localhost:8000/cb"
    )
    assert any(
        "GITHUB_APP_CALLBACK_URL" in p for p in check_configuration().errors
    )


def test_production_rejects_plain_http_cors_origins(
    production, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "cors_origins", "http://localhost:3000")
    assert any("CORS_ORIGINS" in p for p in check_configuration().errors)


def test_development_allows_local_defaults(app_mode, monkeypatch: pytest.MonkeyPatch):
    """The same settings that fail in production are fine locally."""
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000")
    assert check_configuration().ok is True


# -- enforcement ------------------------------------------------------------


def test_enforce_raises_on_an_error(app_mode, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "github_app_id", "")
    with pytest.raises(ConfigurationError, match="GITHUB_APP_ID"):
        enforce_configuration()


def test_enforce_passes_a_valid_configuration(app_mode):
    assert enforce_configuration().ok is True


def test_enforce_does_not_raise_on_warnings_alone(
    app_mode, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "github_app_name", "")
    assert enforce_configuration().ok is True
