import pytest

from app.core.config import settings
from app.llm.profiles import (
    PHASES,
    TASK_PHASES,
    ModelSpec,
    estimate_profile,
    get_profiles,
    resolve_specs,
)


def test_builtin_profiles_match_spec():
    profiles = get_profiles()
    assert set(profiles) == {"cheap", "balanced", "premium"}
    assert profiles["cheap"]["planning"] == ModelSpec("google", "gemini-3.5-flash")
    assert profiles["balanced"]["analysis"] == ModelSpec("google", "gemini-3.5-flash")
    assert profiles["balanced"]["coding"] == ModelSpec("anthropic", "claude-sonnet-5")
    assert profiles["premium"]["coding"] == ModelSpec("anthropic", "claude-opus-4-8")
    for profile in profiles.values():
        assert set(profile) == set(PHASES)


def test_profiles_are_configuration_not_code(monkeypatch: pytest.MonkeyPatch):
    """Changing profile models requires only env/settings changes."""
    monkeypatch.setattr(settings, "profile_premium_provider", "google")
    monkeypatch.setattr(settings, "profile_premium_model", "gemini-2.5-pro")
    assert get_profiles()["premium"]["coding"] == ModelSpec("google", "gemini-2.5-pro")


def test_resolution_precedence(monkeypatch: pytest.MonkeyPatch):
    # 1. Task custom provider+model wins over everything.
    specs = resolve_specs("google", "gemini-2.5-pro", "premium", "anthropic", "m", "cheap")
    assert specs["coding"] == ModelSpec("google", "gemini-2.5-pro")

    # 2. Task profile beats project settings.
    specs = resolve_specs(None, None, "premium", "google", "gemini-2.5-flash", "cheap")
    assert specs["coding"] == ModelSpec("anthropic", "claude-opus-4-8")

    # 3. Project custom provider+model.
    specs = resolve_specs(None, None, None, "google", "gemini-2.5-flash", None)
    assert specs["planning"] == ModelSpec("google", "gemini-2.5-flash")

    # 4. Project profile.
    specs = resolve_specs(None, None, None, None, None, "cheap")
    assert specs["coding"] == ModelSpec("google", "gemini-3.5-flash")

    # 5. Global LLM_PROVIDER + DEFAULT_MODEL — provider switching without code.
    monkeypatch.setattr(settings, "llm_provider", "google")
    monkeypatch.setattr(settings, "default_model", "gemini-2.5-pro")
    specs = resolve_specs(None, None, None, None, None, None)
    assert specs["coding"] == ModelSpec("google", "gemini-2.5-pro")

    # 6. Nothing set anywhere -> balanced profile.
    monkeypatch.setattr(settings, "default_model", "")
    specs = resolve_specs(None, None, None, None, None, None)
    assert specs["coding"] == ModelSpec("anthropic", "claude-sonnet-5")


def test_estimates_before_execution():
    profiles = get_profiles()
    cheap = estimate_profile(profiles["cheap"], TASK_PHASES)
    balanced = estimate_profile(profiles["balanced"], TASK_PHASES)
    premium = estimate_profile(profiles["premium"], TASK_PHASES)

    for estimate in (cheap, balanced, premium):
        assert estimate["estimated_cost_usd"] is not None
        assert estimate["estimated_cost_usd"] > 0
        assert estimate["estimated_latency_seconds"] > 0
    # Ordering must reflect the pricing tiers.
    assert (
        cheap["estimated_cost_usd"]
        < balanced["estimated_cost_usd"]
        < premium["estimated_cost_usd"]
    )


def test_estimate_unknown_model_reports_unknown_cost(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "profile_cheap_model", "mystery-model-9")
    estimate = estimate_profile(get_profiles()["cheap"], TASK_PHASES)
    assert estimate["estimated_cost_usd"] is None
    assert estimate["estimated_latency_seconds"] > 0
