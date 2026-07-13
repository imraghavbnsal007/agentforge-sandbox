"""Regression tests for the provider-independent JSON extraction pipeline."""

import json

import pytest

from app.llm.json_extract import (
    JSONExtractionError,
    ParseDiagnostics,
    _repair_truncated,
    extract_json_object,
    sanitize_preview,
)

CLEAN = {"summary": "ok", "suggestions": []}


def test_clean_json_parses_directly():
    data, stage = extract_json_object(json.dumps(CLEAN))
    assert data == CLEAN and stage == "direct"


def test_provider_parsed_object_wins():
    data, stage = extract_json_object("garbage", parsed={"summary": "p"})
    assert data == {"summary": "p"} and stage == "provider_parsed"


def test_non_dict_parsed_falls_through_to_text():
    data, stage = extract_json_object(json.dumps(CLEAN), parsed=["not", "a", "dict"])
    assert data == CLEAN and stage == "direct"


def test_json_fence_with_language_tag():
    data, stage = extract_json_object(f"```json\n{json.dumps(CLEAN)}\n```")
    assert data == CLEAN and stage == "fenced"


def test_generic_fence_without_language_tag():
    data, stage = extract_json_object(f"```\n{json.dumps(CLEAN)}\n```")
    assert data == CLEAN and stage == "fenced"


def test_leading_and_trailing_prose():
    text = f"Here is the analysis you asked for:\n{json.dumps(CLEAN)}\nHope this helps!"
    data, stage = extract_json_object(text)
    assert data == CLEAN and stage == "balanced_scan"


def test_bom_and_whitespace():
    data, stage = extract_json_object("﻿  \n" + json.dumps(CLEAN) + "  \n")
    assert data == CLEAN and stage == "direct"


def test_trailing_comma_repair():
    data, _ = extract_json_object('{"summary": "ok", "risk_areas": ["a", "b",],}')
    assert data == {"summary": "ok", "risk_areas": ["a", "b"]}


def test_unescaped_control_chars_in_strings():
    # Literal newline inside a string is invalid strict JSON.
    data, _ = extract_json_object('{"summary": "line one\nline two"}')
    assert data["summary"] == "line one\nline two"


def test_first_balanced_object_wins_over_later_ones():
    text = 'noise {"summary": "first"} more noise {"summary": "second"}'
    data, stage = extract_json_object(text)
    assert data == {"summary": "first"} and stage == "balanced_scan"


def test_braces_inside_strings_do_not_confuse_the_scanner():
    obj = {"summary": 'has "quoted" text and } brace and { brace'}
    text = "prose " + json.dumps(obj) + " prose"
    data, _ = extract_json_object(text)
    assert data == obj


def test_truncated_json_repaired():
    """JSON that starts with { but is cut off gets repaired, not rejected."""
    truncated = json.dumps(CLEAN)[:-1]  # remove trailing }
    data, stage = extract_json_object(truncated)
    assert stage == "truncation_repair"
    assert data["summary"] == "ok"


def test_unbalanced_with_leading_prose_tries_repair():
    truncated = json.dumps(CLEAN)[:-8]
    # With leading prose the balanced-scan start shifts; repair applies to
    # the first '{' onwards if nothing earlier worked.
    with pytest.raises(JSONExtractionError) as excinfo:
        extract_json_object("intro " + truncated)
    assert excinfo.value.stage == "truncation_repair"


def test_empty_response_raises():
    with pytest.raises(JSONExtractionError) as excinfo:
        extract_json_object("   \n  ")
    assert excinfo.value.stage == "direct"
    assert "empty" in str(excinfo.value)


def test_top_level_array_is_not_an_object():
    # An array is valid JSON but not the object we need; the balanced
    # scanner may still find a dict inside it.
    data, stage = extract_json_object('[{"summary": "inner"}]')
    assert data == {"summary": "inner"} and stage == "balanced_scan"


def test_never_invents_data():
    with pytest.raises(JSONExtractionError):
        extract_json_object("The repository looks great, no JSON here.")


# -- _repair_truncated -------------------------------------------------------


def test_repair_truncated_mid_string_value():
    text = '{"summary": "some text that gets trunca'
    repaired = _repair_truncated(text)
    assert repaired is not None
    obj = json.loads(repaired)
    assert obj["summary"] == "some text that gets trunca"


def test_repair_truncated_after_complete_value():
    text = '{"summary": "ok", "suggestions": [{"title": "x"}'
    repaired = _repair_truncated(text)
    assert repaired is not None
    obj = json.loads(repaired)
    assert obj["summary"] == "ok"
    assert obj["suggestions"][0]["title"] == "x"


def test_repair_truncated_after_trailing_comma():
    text = '{"summary": "ok", "suggestions": [{"title": "x"},'
    repaired = _repair_truncated(text)
    assert repaired is not None
    obj = json.loads(repaired)
    assert len(obj["suggestions"]) == 1


def test_repair_truncated_mid_key():
    text = '{"summary": "ok", "archite'
    repaired = _repair_truncated(text)
    assert repaired is not None
    obj = json.loads(repaired)
    assert obj["summary"] == "ok"


def test_repair_truncated_after_colon():
    text = '{"summary": "ok", "risk_areas":'
    repaired = _repair_truncated(text)
    assert repaired is not None
    obj = json.loads(repaired)
    assert obj["summary"] == "ok"
    assert "risk_areas" not in obj


def test_repair_returns_none_for_balanced_json():
    text = json.dumps(CLEAN)
    assert _repair_truncated(text) is None


def test_repair_returns_none_for_non_object():
    assert _repair_truncated("just text") is None
    assert _repair_truncated("") is None
    assert _repair_truncated("[1,2,3") is None


def test_repair_handles_escaped_quotes():
    text = r'{"summary": "has \"escaped\" quotes and trunca'
    repaired = _repair_truncated(text)
    assert repaired is not None
    obj = json.loads(repaired)
    assert "escaped" in obj["summary"]


def test_repair_deeply_nested():
    text = '{"a": {"b": [{"c": "val'
    repaired = _repair_truncated(text)
    assert repaired is not None
    obj = json.loads(repaired)
    assert obj["a"]["b"][0]["c"] == "val"


def test_repair_integrated_via_extract():
    """Truncated JSON goes through the full pipeline and lands on truncation_repair."""
    text = '{"summary": "truncated analysis", "suggestions": [{"title": "add tests", "description": "tests are'
    data, stage = extract_json_object(text)
    assert stage == "truncation_repair"
    assert data["summary"] == "truncated analysis"
    assert data["suggestions"][0]["title"] == "add tests"


# -- sanitize_preview -------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-abcdefghijklmnop",
        "AIzaSyD-1234567890abcdefg",
        "ghp_abcdefghijklmnopqrstuvwx",
        "github_pat_ABCDEF1234567890",
        "Bearer abc.def-ghi_jkl12345",
        "whsec_abcdef1234567890",
    ],
)
def test_sanitize_preview_redacts_secret_tokens(secret):
    sanitized = sanitize_preview(f"response containing {secret} inline")
    assert secret not in sanitized
    assert "[REDACTED]" in sanitized


def test_sanitize_preview_redacts_key_value_pairs():
    sanitized = sanitize_preview('config: api_key="supersecretvalue" password=hunter22x')
    assert "supersecretvalue" not in sanitized
    assert "hunter22x" not in sanitized
    assert "api_key" in sanitized  # key names stay for debuggability


def test_sanitize_preview_truncates_to_limit():
    sanitized = sanitize_preview("x" * 5000)
    assert sanitized.startswith("x" * 1000)
    assert "[5000 chars total]" in sanitized


def test_sanitize_preview_leaves_normal_text_alone():
    text = '{"summary": "a normal analysis of calculator.py"}'
    assert sanitize_preview(text) == text


# -- ParseDiagnostics -------------------------------------------------------


def test_diagnostics_from_failure_captures_everything_safely():
    exc = JSONExtractionError("balanced_scan", "no parseable JSON")
    raw = 'prose with sk-ant-api03-secretsecret inside {"broken": '
    diag = ParseDiagnostics.from_failure(
        provider="google",
        model="gemini-3.5-flash",
        response_text=raw,
        exc=exc,
        mime_type="application/json",
        finish_reason="MAX_TOKENS",
    )
    assert diag.provider == "google"
    assert diag.model == "gemini-3.5-flash"
    assert diag.response_length == len(raw)
    assert diag.failed_stage == "balanced_scan"
    assert diag.exception_type == "JSONExtractionError"
    assert diag.finish_reason == "MAX_TOKENS"
    assert len(diag.response_sha256) == 12
    assert "sk-ant-api03-secretsecret" not in diag.preview

    rendered = diag.render()
    assert "provider=google" in rendered
    assert "finish_reason=MAX_TOKENS" in rendered
    assert "sk-ant-api03-secretsecret" not in rendered
