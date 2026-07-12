"""Tests for the typed enrichment schema: required fields fail loudly,
optional fields default safely, enum-ish fields normalize."""

import pytest

from app.llm.analysis_schema import (
    ENRICHMENT_JSON_SCHEMA,
    SchemaValidationError,
    validate_enrichment,
)

MINIMAL = {"summary": "A project.", "suggestions": []}


def test_minimal_valid_object_fills_defaults():
    result = validate_enrichment(MINIMAL)
    assert result.summary == "A project."
    assert result.suggestions == []
    assert result.architecture_notes == ""
    assert result.risk_areas == []
    assert result.file_purposes == []


def test_missing_summary_names_the_field():
    with pytest.raises(SchemaValidationError, match="summary"):
        validate_enrichment({"suggestions": []})


def test_missing_suggestions_names_the_field():
    with pytest.raises(SchemaValidationError, match="suggestions"):
        validate_enrichment({"summary": "ok"})


def test_wrong_type_on_required_field_fails():
    with pytest.raises(SchemaValidationError, match="suggestions"):
        validate_enrichment({"summary": "ok", "suggestions": "not a list"})


def test_validation_error_has_stage_for_diagnostics():
    try:
        validate_enrichment({})
    except SchemaValidationError as exc:
        assert exc.stage == "validation"
    else:
        pytest.fail("expected SchemaValidationError")


def test_full_suggestion_roundtrip():
    result = validate_enrichment(
        {
            **MINIMAL,
            "suggestions": [
                {
                    "title": "Add tests for calculator.py",
                    "description": "Edge cases are uncovered.",
                    "category": "testing",
                    "priority": "high",
                    "confidence": "low",
                    "estimated_effort": "small",
                    "related_files": ["calculator.py"],
                    "reasoning": "Only happy paths tested.",
                }
            ],
        }
    )
    s = result.suggestions[0]
    assert s.category == "testing" and s.priority == "high"
    assert s.confidence == "low" and s.estimated_effort == "small"


def test_invalid_enum_values_normalize_to_defaults():
    result = validate_enrichment(
        {
            **MINIMAL,
            "suggestions": [
                {
                    "title": "t",
                    "category": "NONSENSE",
                    "priority": "URGENT!!",
                    "confidence": "absolutely",
                    "estimated_effort": "gigantic",
                }
            ],
        }
    )
    s = result.suggestions[0]
    assert s.category == "quality" and s.priority == "medium"
    assert s.confidence == "medium" and s.estimated_effort == "medium"


def test_enum_values_case_insensitive():
    result = validate_enrichment(
        {**MINIMAL, "suggestions": [{"title": "t", "priority": " High "}]}
    )
    assert result.suggestions[0].priority == "high"


def test_suggestion_without_title_fails():
    with pytest.raises(SchemaValidationError, match="title"):
        validate_enrichment({**MINIMAL, "suggestions": [{"description": "no title"}]})


def test_related_files_string_coerced_to_list():
    result = validate_enrichment(
        {**MINIMAL, "suggestions": [{"title": "t", "related_files": "single.py"}]}
    )
    assert result.suggestions[0].related_files == ["single.py"]


def test_risk_areas_string_coerced_to_list():
    result = validate_enrichment({**MINIMAL, "risk_areas": "one risk"})
    assert result.risk_areas == ["one risk"]
    result = validate_enrichment({**MINIMAL, "risk_areas": "  "})
    assert result.risk_areas == []


def test_importance_score_clamped_and_defaulted():
    result = validate_enrichment(
        {
            **MINIMAL,
            "file_purposes": [
                {"file_path": "a.py", "importance_score": 250},
                {"file_path": "b.py", "importance_score": -5},
                {"file_path": "c.py", "importance_score": "87"},
                {"file_path": "d.py", "importance_score": "not a number"},
                {"file_path": "e.py"},
            ],
        }
    )
    scores = [fp.importance_score for fp in result.file_purposes]
    assert scores == [100, 0, 87, 50, 50]


def test_file_purpose_requires_path():
    with pytest.raises(SchemaValidationError, match="file_path"):
        validate_enrichment({**MINIMAL, "file_purposes": [{"purpose": "no path"}]})


def test_unknown_extra_keys_are_ignored_not_fatal():
    result = validate_enrichment({**MINIMAL, "hallucinated_key": {"x": 1}})
    assert result.summary == "A project."


def test_json_schema_export_marks_required_fields():
    assert set(ENRICHMENT_JSON_SCHEMA["required"]) == {"summary", "suggestions"}
    assert "properties" in ENRICHMENT_JSON_SCHEMA
    assert "file_purposes" in ENRICHMENT_JSON_SCHEMA["properties"]
