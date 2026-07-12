"""Provider-neutral request/response types for all LLM interactions.

Business logic (runners, analysis, services) speaks only these types —
provider SDK objects never leave app/llm/providers/*.
"""

from dataclasses import dataclass, field


class LLMProviderError(Exception):
    """A provider failed in a way business logic should handle gracefully.

    Messages are always safe to show users and log — providers scrub keys.
    """


class AnalysisParseError(LLMProviderError):
    """A repository-analysis response could not be parsed as JSON.

    Carries sanitized ParseDiagnostics so callers can persist a debuggable
    record without ever touching the raw (potentially huge) response.
    """

    def __init__(self, message: str, diagnostics: object | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


@dataclass
class LLMToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    stop_reason: str = "end"  # "end" | "tool_use" | "max_tokens"
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    # Provider-opaque copy of the model turn, replayed verbatim on the next
    # request when present. Some APIs require this: Gemini thinking models
    # reject reconstructed function-call parts that lack thought_signature.
    raw: object | None = None
    # Provider-parsed structured output (e.g. Gemini response.parsed when a
    # JSON schema was requested). Preferred over re-parsing `text`.
    parsed: object | None = None
    # Provider's verbatim finish reason (e.g. "STOP", "MAX_TOKENS") and the
    # response MIME type when structured output was requested — diagnostics
    # only, never used for control flow.
    finish_reason: str = ""
    mime_type: str = ""


# Neutral message format:
#   {"role": "user" | "assistant", "content": [block, ...]}
# blocks:
#   {"type": "text", "text": str}
#   {"type": "tool_call", "id": str, "name": str, "input": dict}          (assistant)
#   {"type": "tool_result", "tool_call_id": str, "name": str,
#    "content": str, "is_error": bool}                                    (user)
Message = dict


def text_message(role: str, text: str) -> Message:
    return {"role": role, "content": [{"type": "text", "text": text}]}
