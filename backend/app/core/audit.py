"""Structured audit events for security-relevant actions.

Emitted on a dedicated `agentforge.audit` logger so deployments can route
them somewhere durable without mixing them into application logs.

Rule: audit records identify *who did what, from where, and whether it
worked*. They never contain tokens, codes, secrets, or repository contents.
`_SENSITIVE_FIELDS` is a backstop against a careless caller.
"""

import logging
from typing import Any

logger = logging.getLogger("agentforge.audit")

# Never recorded, whatever the caller passes.
_SENSITIVE_FIELDS = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "code",
        "client_secret",
        "password",
        "secret",
        "authorization",
        "session_id",
        "csrf_token",
        "private_key",
    }
)

# Authentication events.
LOGIN_STARTED = "auth.login.started"
LOGIN_SUCCEEDED = "auth.login.succeeded"
LOGIN_FAILED = "auth.login.failed"
LOGOUT = "auth.logout"
SESSION_REJECTED = "auth.session.rejected"
RATE_LIMITED = "auth.rate_limited"
CSRF_REJECTED = "auth.csrf.rejected"


def audit(event: str, **fields: Any) -> None:
    safe = {
        key: value
        for key, value in fields.items()
        if key.lower() not in _SENSITIVE_FIELDS and value is not None
    }
    detail = " ".join(f"{key}={value!r}" for key, value in sorted(safe.items()))
    logger.info("%s %s", event, detail, extra={"audit_event": event, **safe})
