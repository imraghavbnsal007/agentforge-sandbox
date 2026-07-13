"""Provider-independent JSON extraction from LLM responses, with safe
diagnostics.

Ordered strategy (each stage only runs if the previous failed):
  1. provider_parsed — the provider's structured/parsed object, if any
  2. direct          — json.loads on the cleaned text
  3. fenced          — strip ```json / ``` fences, parse again
  4. balanced_scan   — first balanced top-level JSON object in the text

Repairs are deterministic only: BOM/whitespace stripping, control characters
inside strings (strict=False), and trailing commas before } or ]. The parser
never invents data — if nothing parses, it raises with the failing stage.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)
MAX_BALANCED_CANDIDATES = 20
PREVIEW_LIMIT = 1000

# Secret-looking values to redact from any logged preview. Keep the key name,
# hide the value.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"(?:github_pat|ghp|gho|ghs)_[A-Za-z0-9_]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"whsec_[A-Za-z0-9]{8,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization|credential)"
        r"(\"?\s*[:=]\s*\"?)([^\s\"',;}{\]]{6,})"
    ),
]


class JSONExtractionError(Exception):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


def sanitize_preview(text: str, limit: int = PREVIEW_LIMIT) -> str:
    """Redact secret-looking values, then truncate."""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    if len(text) > limit:
        return text[:limit] + f"… [{len(text)} chars total]"
    return text


def _clean(text: str) -> str:
    return text.lstrip("\ufeff").strip()


def _try_loads(candidate: str):
    """json.loads with deterministic repairs; returns dict or raises."""
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Control characters inside strings (unescaped newlines/tabs).
    try:
        return json.loads(candidate, strict=False)
    except json.JSONDecodeError:
        pass
    # Trailing commas before } or ] — a safe, deterministic repair.
    repaired = _TRAILING_COMMA_RE.sub(r"\1", candidate)
    return json.loads(repaired, strict=False)


def _repair_truncated(text: str) -> str | None:
    """Best-effort repair of JSON truncated mid-generation (MAX_TOKENS).

    Walks the text tracking bracket nesting and string state.  If the text
    ends with unclosed structures, closes them.  Returns the repaired
    string, or None if already balanced or not starting with '{'.
    """
    if not text or text[0] != "{":
        return None

    stack: list[str] = []
    in_string = False
    escaped = False
    stripped_colon = False

    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in ("}", "]") and stack:
                stack.pop()

    if not stack:
        return None

    result = text
    if in_string:
        result += '"'

    result = result.rstrip()
    while result and result[-1] in (",", ":"):
        if result[-1] == ":":
            stripped_colon = True
        result = result[:-1].rstrip()

    if stripped_colon and result.endswith('"'):
        q = result.rfind('"', 0, len(result) - 1)
        if q >= 0:
            result = result[:q].rstrip().rstrip(",").rstrip()

    if in_string and result.endswith('"'):
        q = result.rfind('"', 0, len(result) - 1)
        if q >= 0:
            before = result[:q].rstrip()
            if before and before[-1] in (",", "{", "["):
                result = before.rstrip(",").rstrip()

    result += "".join(reversed(stack))
    return result


def _balanced_objects(text: str):
    """Yield candidate substrings that are balanced top-level {...} objects."""
    yielded = 0
    search_from = 0
    while yielded < MAX_BALANCED_CANDIDATES:
        start = text.find("{", search_from)
        if start == -1:
            return
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yielded += 1
                    yield text[start : i + 1]
                    break
        else:
            return  # ran out of text with unbalanced braces
        search_from = start + 1


def extract_json_object(
    text: str, parsed: object | None = None
) -> tuple[dict, str]:
    """Returns (object, stage_name). Raises JSONExtractionError otherwise."""
    # 1. Provider's structured/parsed object.
    if isinstance(parsed, dict):
        return parsed, "provider_parsed"

    cleaned = _clean(text or "")
    if not cleaned:
        raise JSONExtractionError("direct", "response is empty")

    # 2. Direct parse.
    try:
        obj = _try_loads(cleaned)
        if isinstance(obj, dict):
            return obj, "direct"
    except json.JSONDecodeError:
        pass

    # 3. Strip Markdown fences.
    unfenced = _FENCE_RE.sub("", cleaned).strip()
    if unfenced != cleaned:
        try:
            obj = _try_loads(unfenced)
            if isinstance(obj, dict):
                return obj, "fenced"
        except json.JSONDecodeError:
            pass

    # 4. First balanced top-level object anywhere in the text.
    for candidate in _balanced_objects(cleaned):
        try:
            obj = _try_loads(candidate)
            if isinstance(obj, dict):
                return obj, "balanced_scan"
        except json.JSONDecodeError:
            continue

    # 5. Truncation repair — close unclosed brackets (MAX_TOKENS cutoff).
    repaired = _repair_truncated(cleaned)
    if repaired is not None:
        try:
            obj = _try_loads(repaired)
            if isinstance(obj, dict):
                return obj, "truncation_repair"
        except json.JSONDecodeError:
            pass

    raise JSONExtractionError(
        "truncation_repair", "no parseable top-level JSON object found in response"
    )


@dataclass
class ParseDiagnostics:
    """Everything needed to debug a parse failure — and nothing secret."""

    provider: str = ""
    model: str = ""
    response_length: int = 0
    mime_type: str = ""
    finish_reason: str = ""
    failed_stage: str = ""
    exception_type: str = ""
    exception_message: str = ""
    preview: str = ""
    response_sha256: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_failure(
        cls,
        provider: str,
        model: str,
        response_text: str,
        exc: Exception,
        mime_type: str = "",
        finish_reason: str = "",
    ) -> "ParseDiagnostics":
        return cls(
            provider=provider,
            model=model,
            response_length=len(response_text or ""),
            mime_type=mime_type,
            finish_reason=finish_reason,
            failed_stage=getattr(exc, "stage", "validation"),
            exception_type=type(exc).__name__,
            exception_message=sanitize_preview(str(exc), 500),
            preview=sanitize_preview(response_text or ""),
            response_sha256=hashlib.sha256(
                (response_text or "").encode()
            ).hexdigest()[:12],
        )

    def render(self) -> str:
        lines = [
            "--- enrichment parse diagnostics ---",
            f"provider={self.provider} model={self.model}",
            f"response_length={self.response_length} sha256={self.response_sha256}",
            f"mime_type={self.mime_type or 'unknown'} finish_reason={self.finish_reason or 'unknown'}",
            f"failed_stage={self.failed_stage} exception={self.exception_type}: {self.exception_message}",
            "response preview (sanitized, first 1000 chars):",
            self.preview or "(empty)",
            "--- end diagnostics ---",
        ]
        return "\n".join(lines)
