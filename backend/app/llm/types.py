"""Provider-neutral request/response types for all LLM interactions.

Business logic (runners, analysis, services) speaks only these types —
provider SDK objects never leave app/llm/providers/*.
"""

from dataclasses import dataclass, field


class LLMProviderError(Exception):
    """A provider failed in a way business logic should handle gracefully.

    Messages are always safe to show users and log — providers scrub keys.
    """


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
