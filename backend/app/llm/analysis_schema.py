"""Typed contract for the repository-analysis AI enrichment result.

Required fields: `summary` and `suggestions`. Everything else is optional
with safe defaults — a missing optional field must never sink an analysis.
Enum-ish string fields are normalized to their allowed sets instead of
failing; wrong *types* on required fields fail validation with a message
naming exactly what was wrong.
"""

from pydantic import BaseModel, Field, ValidationError, field_validator

VALID_CATEGORIES = {"testing", "docs", "structure", "security", "quality"}
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_EFFORT = {"small", "medium", "large"}


class SchemaValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.stage = "validation"


def _normalize(value: object, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


class FilePurpose(BaseModel):
    file_path: str
    purpose: str = ""
    importance_score: int = Field(default=50)

    @field_validator("importance_score", mode="before")
    @classmethod
    def _clamp_importance(cls, value):
        try:
            return max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return 50


class EnrichmentSuggestion(BaseModel):
    title: str
    description: str = ""
    category: str = "quality"
    priority: str = "medium"
    confidence: str = "medium"
    estimated_effort: str = "medium"
    related_files: list[str] = Field(default_factory=list)
    reasoning: str = ""

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v):
        return _normalize(v, VALID_CATEGORIES, "quality")

    @field_validator("priority", mode="before")
    @classmethod
    def _pri(cls, v):
        return _normalize(v, VALID_PRIORITIES, "medium")

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v):
        return _normalize(v, VALID_CONFIDENCE, "medium")

    @field_validator("estimated_effort", mode="before")
    @classmethod
    def _eff(cls, v):
        return _normalize(v, VALID_EFFORT, "medium")

    @field_validator("related_files", mode="before")
    @classmethod
    def _files(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v


class EnrichmentResult(BaseModel):
    # Required — their absence or wrong type fails validation.
    summary: str
    suggestions: list[EnrichmentSuggestion]
    # Optional with safe defaults.
    architecture_notes: str = ""
    risk_areas: list[str] = Field(default_factory=list)
    file_purposes: list[FilePurpose] = Field(default_factory=list)

    @field_validator("risk_areas", mode="before")
    @classmethod
    def _risks(cls, v):
        # Models sometimes return a single string; that's coercion, not invention.
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v


def validate_enrichment(data: dict) -> EnrichmentResult:
    """Validate a parsed object; on failure name the offending fields."""
    try:
        return EnrichmentResult.model_validate(data)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            location = ".".join(str(p) for p in error["loc"]) or "(root)"
            problems.append(f"{location}: {error['msg']}")
        raise SchemaValidationError(
            "enrichment result failed schema validation — "
            + "; ".join(problems[:8])
        ) from exc


# JSON Schema handed to providers that support structured output.
ENRICHMENT_JSON_SCHEMA: dict = EnrichmentResult.model_json_schema()
