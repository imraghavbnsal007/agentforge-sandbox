"""GitHub App webhook endpoint.

Deliberately not behind `require_user`: GitHub has no session. The HMAC
signature is the authentication, and it is verified against the **raw** body
before a single byte is parsed.

Response policy: 401 for an unverifiable delivery, 503 when no secret is
configured, and 200 for everything that passes — including events we do not
handle. A non-2xx makes GitHub retry, so it is reserved for deliveries we
genuinely want redelivered.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, KV
from app.core.audit import (
    WEBHOOK_DUPLICATE,
    WEBHOOK_FAILED,
    WEBHOOK_IGNORED,
    WEBHOOK_PROCESSED,
    WEBHOOK_RECEIVED,
    WEBHOOK_REJECTED,
    audit,
)
from app.core.config import settings
from app.core.ratelimit import RateLimiter
from app.core.security import client_ip
from app.models.webhook_delivery import (
    STATUS_FAILED,
    STATUS_IGNORED,
    STATUS_PROCESSED,
    WebhookDelivery,
)
from app.services.webhook_handler import (
    SUPPORTED_EVENTS,
    WebhookHandler,
    installation_id_from,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/github", tags=["github-webhooks"])

SIGNATURE_HEADER = "X-Hub-Signature-256"
EVENT_HEADER = "X-GitHub-Event"
DELIVERY_HEADER = "X-GitHub-Delivery"
SIGNATURE_PREFIX = "sha256="


def verify_signature(raw_body: bytes, provided: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 check over the exact bytes GitHub sent.

    The raw body matters: re-serialising the parsed JSON would change
    whitespace and key order, producing a different digest.
    """
    if not provided or not provided.startswith(SIGNATURE_PREFIX):
        return False
    expected = SIGNATURE_PREFIX + hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


@router.post("/webhooks")
async def receive_webhook(
    request: Request, db: DbSession, kv: KV
) -> Response:
    ip = client_ip(request)
    event = request.headers.get(EVENT_HEADER, "")
    delivery_id = request.headers.get(DELIVERY_HEADER, "")

    if not settings.webhooks_configured():
        # Refuse rather than accept something we cannot verify.
        audit(WEBHOOK_REJECTED, reason="no_secret_configured", ip=ip)
        return Response(
            content=json.dumps(
                {"detail": "Webhooks are not configured on this server"}
            ),
            status_code=503,
            media_type="application/json",
        )

    # Raw bytes, read before any parsing.
    raw_body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER, "")

    if not verify_signature(
        raw_body, signature, settings.github_app_webhook_secret
    ):
        # Only failures are rate limited, so a legitimate GitHub burst is
        # never throttled while a flood of forgeries is.
        limiter = RateLimiter(
            kv,
            limit=settings.webhook_rate_limit_requests,
            window_seconds=settings.webhook_rate_limit_window_seconds,
        )
        try:
            await limiter.check("webhook_invalid", ip)
        except Exception:  # RateLimitedError -> handled by the app handler
            raise
        audit(
            WEBHOOK_REJECTED,
            reason="missing_signature" if not signature else "bad_signature",
            event=event or None,
            delivery_id=delivery_id or None,
            ip=ip,
        )
        return Response(
            content=json.dumps({"detail": "Invalid webhook signature"}),
            status_code=401,
            media_type="application/json",
        )

    if not delivery_id:
        audit(WEBHOOK_REJECTED, reason="missing_delivery_id", event=event, ip=ip)
        return Response(
            content=json.dumps({"detail": "Missing delivery id"}),
            status_code=400,
            media_type="application/json",
        )

    try:
        payload = json.loads(raw_body or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except ValueError:
        audit(WEBHOOK_REJECTED, reason="unparseable_body", event=event, ip=ip)
        return Response(
            content=json.dumps({"detail": "Unparseable webhook body"}),
            status_code=400,
            media_type="application/json",
        )

    action = str(payload.get("action") or "") or None
    github_installation_id = installation_id_from(payload)
    audit(
        WEBHOOK_RECEIVED,
        event=event,
        action=action,
        delivery_id=delivery_id,
        installation_id=github_installation_id,
    )

    # Insert-first deduplication. The unique constraint — not a prior SELECT —
    # is what makes this safe against two concurrent deliveries of the same
    # id, and against a replay carrying a still-valid signature.
    record = WebhookDelivery(
        delivery_id=delivery_id,
        event=event or "unknown",
        action=action,
        github_installation_id=github_installation_id,
        status=STATUS_PROCESSED,
    )
    db.add(record)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        audit(WEBHOOK_DUPLICATE, event=event, delivery_id=delivery_id)
        return Response(
            content=json.dumps({"detail": "Delivery already processed"}),
            status_code=200,
            media_type="application/json",
        )

    if event not in SUPPORTED_EVENTS:
        record.status = STATUS_IGNORED
        record.processed_at = datetime.now(timezone.utc)
        await db.commit()
        audit(WEBHOOK_IGNORED, event=event, delivery_id=delivery_id)
        return Response(
            content=json.dumps({"detail": "Event not handled"}),
            status_code=200,
            media_type="application/json",
        )

    try:
        changed = await WebhookHandler(db).handle(event, payload)
    except Exception as exc:
        logger.exception("Webhook %s (%s) failed", delivery_id, event)
        await db.rollback()
        record.status = STATUS_FAILED
        record.error = f"{type(exc).__name__}"[:500]
        record.processed_at = datetime.now(timezone.utc)
        await db.commit()
        audit(
            WEBHOOK_FAILED,
            event=event,
            action=action,
            delivery_id=delivery_id,
            error_type=type(exc).__name__,
        )
        # 500 so GitHub redelivers; the ledger row is updated, and the
        # redelivery carries a new delivery id so dedup will not block it.
        return Response(
            content=json.dumps({"detail": "Webhook processing failed"}),
            status_code=500,
            media_type="application/json",
        )

    record.status = STATUS_PROCESSED if changed else STATUS_IGNORED
    record.processed_at = datetime.now(timezone.utc)
    await db.commit()
    audit(
        WEBHOOK_PROCESSED if changed else WEBHOOK_IGNORED,
        event=event,
        action=action,
        delivery_id=delivery_id,
        installation_id=github_installation_id,
    )
    return Response(
        content=json.dumps({"detail": "ok"}),
        status_code=200,
        media_type="application/json",
    )
