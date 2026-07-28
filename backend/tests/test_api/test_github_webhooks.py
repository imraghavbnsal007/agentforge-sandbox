"""Webhook endpoint: signature verification, deduplication, replay
protection and response policy.

Every payload here is locally constructed and signed with a test secret. No
GitHub request is made.
"""

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import GitHubInstallation, WebhookDelivery
from app.models.webhook_delivery import STATUS_IGNORED, STATUS_PROCESSED

SECRET = "test-webhook-secret"
URL = "/api/v1/github/webhooks"


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "github_app_webhook_secret", SECRET)


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _headers(body: bytes, event: str, delivery: str, secret: str = SECRET) -> dict:
    return {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": sign(body, secret),
        "Content-Type": "application/json",
    }


async def post(
    client: AsyncClient,
    payload: dict,
    event: str = "installation",
    delivery: str = "d-1",
    secret: str = SECRET,
    signature: str | None = None,
):
    body = json.dumps(payload).encode()
    headers = _headers(body, event, delivery, secret)
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return await client.post(URL, content=body, headers=headers)


def installation_payload(action: str, installation_id: int = 500, **extra) -> dict:
    payload = {
        "action": action,
        "installation": {
            "id": installation_id,
            "account": {"id": 1, "login": "octocat", "type": "User"},
            "target_type": "User",
            "repository_selection": "selected",
        },
    }
    payload.update(extra)
    return payload


async def _delivery_count(session: AsyncSession) -> int:
    return (
        await session.execute(select(func.count()).select_from(WebhookDelivery))
    ).scalar_one()


# -- signature verification -------------------------------------------------


async def test_valid_signature_is_accepted(client: AsyncClient):
    response = await post(client, installation_payload("created"))
    assert response.status_code == 200


async def test_missing_signature_is_rejected(client: AsyncClient):
    body = json.dumps(installation_payload("created")).encode()
    response = await client.post(
        URL,
        content=body,
        headers={"X-GitHub-Event": "installation", "X-GitHub-Delivery": "d-1"},
    )
    assert response.status_code == 401
    assert "signature" in response.json()["detail"].lower()


async def test_wrong_secret_is_rejected(client: AsyncClient):
    response = await post(client, installation_payload("created"), secret="wrong")
    assert response.status_code == 401


async def test_malformed_signature_header_is_rejected(client: AsyncClient):
    response = await post(
        client, installation_payload("created"), signature="not-a-signature"
    )
    assert response.status_code == 401


async def test_signature_without_the_sha256_prefix_is_rejected(
    client: AsyncClient,
):
    body = json.dumps(installation_payload("created")).encode()
    bare = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = await client.post(
        URL,
        content=body,
        headers={
            "X-GitHub-Event": "installation",
            "X-GitHub-Delivery": "d-1",
            "X-Hub-Signature-256": bare,
        },
    )
    assert response.status_code == 401


async def test_tampered_body_is_rejected(client: AsyncClient):
    """A signature valid for a different body must not authorise this one."""
    original = json.dumps(installation_payload("created")).encode()
    tampered = json.dumps(installation_payload("deleted")).encode()
    response = await client.post(
        URL,
        content=tampered,
        headers={
            "X-GitHub-Event": "installation",
            "X-GitHub-Delivery": "d-1",
            "X-Hub-Signature-256": sign(original),
        },
    )
    assert response.status_code == 401


async def test_rejected_delivery_is_not_recorded(
    client: AsyncClient, session: AsyncSession
):
    await post(client, installation_payload("created"), secret="wrong")
    assert await _delivery_count(session) == 0


async def test_unconfigured_secret_refuses_everything(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Better to refuse than to accept a delivery we cannot verify."""
    monkeypatch.setattr(settings, "github_app_webhook_secret", "")
    response = await post(client, installation_payload("created"))
    assert response.status_code == 503


# -- deduplication / replay -------------------------------------------------


async def test_duplicate_delivery_is_not_reprocessed(
    client: AsyncClient, session: AsyncSession
):
    payload = installation_payload("created")
    first = await post(client, payload, delivery="dup-1")
    second = await post(client, payload, delivery="dup-1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "already processed" in second.json()["detail"]
    assert await _delivery_count(session) == 1


async def test_replayed_delivery_with_valid_signature_is_blocked(
    client: AsyncClient, session: AsyncSession
):
    """The signature stays valid forever — the delivery id is the defence."""
    body = json.dumps(installation_payload("suspend")).encode()
    headers = _headers(body, "installation", "replay-1")

    await client.post(URL, content=body, headers=headers)
    replay = await client.post(URL, content=body, headers=headers)

    assert replay.status_code == 200
    assert "already processed" in replay.json()["detail"]
    assert await _delivery_count(session) == 1


async def test_distinct_deliveries_are_both_processed(
    client: AsyncClient, session: AsyncSession
):
    await post(client, installation_payload("created"), delivery="a")
    await post(client, installation_payload("created"), delivery="b")
    assert await _delivery_count(session) == 2


async def test_missing_delivery_id_is_rejected(client: AsyncClient):
    body = json.dumps(installation_payload("created")).encode()
    response = await client.post(
        URL,
        content=body,
        headers={
            "X-GitHub-Event": "installation",
            "X-Hub-Signature-256": sign(body),
        },
    )
    assert response.status_code == 400


# -- response policy --------------------------------------------------------


async def test_ping_is_acknowledged(client: AsyncClient):
    response = await post(client, {"zen": "hi"}, event="ping", delivery="p-1")
    assert response.status_code == 200


async def test_unhandled_event_is_accepted_and_recorded_as_ignored(
    client: AsyncClient, session: AsyncSession
):
    """A non-2xx would make GitHub retry an event we will never handle."""
    response = await post(
        client, {"action": "opened"}, event="pull_request", delivery="pr-1"
    )
    assert response.status_code == 200

    record = (
        await session.execute(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == "pr-1")
        )
    ).scalar_one()
    assert record.status == STATUS_IGNORED
    assert record.event == "pull_request"


async def test_unparseable_body_is_rejected(client: AsyncClient):
    body = b"not json at all"
    response = await client.post(
        URL,
        content=body,
        headers={
            "X-GitHub-Event": "installation",
            "X-GitHub-Delivery": "bad-json",
            "X-Hub-Signature-256": sign(body),
        },
    )
    assert response.status_code == 400


async def test_delivery_record_captures_context(
    client: AsyncClient, session: AsyncSession
):
    await post(client, installation_payload("created", 777), delivery="ctx-1")
    record = (
        await session.execute(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == "ctx-1")
        )
    ).scalar_one()
    assert record.event == "installation"
    assert record.action == "created"
    assert record.github_installation_id == 777
    assert record.status == STATUS_PROCESSED
    assert record.processed_at is not None


# -- authentication boundary ------------------------------------------------


async def test_webhook_needs_no_session(client: AsyncClient):
    """GitHub has no cookie; the HMAC is the authentication."""
    response = await post(client, installation_payload("created"))
    assert response.status_code == 200


async def test_webhook_works_in_github_app_mode(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    from app.core.enums import AuthMode

    monkeypatch.setattr(settings, "auth_mode", AuthMode.github_app)
    response = await post(client, installation_payload("created"))
    assert response.status_code == 200


# -- end-to-end state change ------------------------------------------------


async def test_created_event_stores_the_installation(
    client: AsyncClient, session: AsyncSession
):
    await post(client, installation_payload("created", 900), delivery="new-1")
    installation = (
        await session.execute(
            select(GitHubInstallation).where(
                GitHubInstallation.github_installation_id == 900
            )
        )
    ).scalar_one()
    assert installation.account_login == "octocat"
    assert installation.is_active is True
