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
        "signature",
        "x-hub-signature-256",
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

# Webhook events.
WEBHOOK_RECEIVED = "github.webhook.received"
WEBHOOK_REJECTED = "github.webhook.rejected"
WEBHOOK_DUPLICATE = "github.webhook.duplicate"
WEBHOOK_PROCESSED = "github.webhook.processed"
WEBHOOK_IGNORED = "github.webhook.ignored"
WEBHOOK_FAILED = "github.webhook.failed"
INSTALLATION_REVOKED = "github.installation.revoked"
INSTALLATION_UNSUSPENDED = "github.installation.unsuspended"
REPOSITORIES_ADDED = "github.repositories.added"
REPOSITORIES_REMOVED = "github.repositories.removed"


def audit(event_name: str, **fields: Any) -> None:
    """Record one audit event.

    The first parameter is `event_name`, not `event`, so callers can pass a
    field literally named `event` (webhooks carry a GitHub event type).
    """
    safe = {
        key: value
        for key, value in fields.items()
        if key.lower() not in _SENSITIVE_FIELDS and value is not None
    }
    detail = " ".join(f"{key}={value!r}" for key, value in sorted(safe.items()))
    logger.info(
        "%s %s", event_name, detail, extra={"audit_event": event_name, **safe}
    )
