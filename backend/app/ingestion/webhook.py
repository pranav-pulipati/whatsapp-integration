"""Webhook ingestion endpoint.

Does only cheap work: authenticate → validate → dedupe → persist → 200.
All parsing into contacts/conversations/messages happens in the worker.

URL: POST /webhooks/{provider}/{webhook_token}
Each WhatsApp number has its own unguessable token, which also tells us which
number the event belongs to before we even parse the body.
"""

import hashlib
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import WebhookEvent, WhatsAppAccount
from app.providers.base import WebhookAuthError
from app.providers.registry import PROVIDER_NAMES, get_provider
from app.ratelimit import webhook_limiter
from app.security import constant_time_equals

log = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


def store_event(
    db: Session,
    *,
    provider: str,
    account_id: int | None,
    payload: dict[str, Any],
    raw: bytes,
    kind: str | None,
    source: str = "webhook",
    ignore_reason: str | None = None,
) -> int | None:
    """Insert a raw event into the processing queue. Returns the new id, or None
    if an identical payload was already stored (duplicate delivery)."""
    status = "ignored" if ignore_reason or kind is None else "pending"
    stmt = (
        insert(WebhookEvent)
        .values(
            provider=provider,
            account_id=account_id,
            source=source,
            event_kind=kind,
            payload=payload,
            payload_sha256=hashlib.sha256(raw).hexdigest(),
            status=status,
            last_error=ignore_reason or (None if kind else "unrecognised payload shape"),
        )
        .on_conflict_do_nothing(constraint="uq_webhook_events_provider_sha")
        .returning(WebhookEvent.id)
    )
    event_id = db.execute(stmt).scalar_one_or_none()
    db.commit()
    return event_id


def _ingest(
    db: Session, provider_name: str, token: str, headers: dict[str, str], body: bytes
) -> dict[str, Any]:
    provider = get_provider(provider_name)

    account = db.execute(
        select(WhatsAppAccount).where(
            WhatsAppAccount.webhook_token == token, WhatsAppAccount.provider == provider_name
        )
    ).scalar_one_or_none()
    if account is None:
        raise ApiError(404, "not_found", "Unknown webhook")

    try:
        provider.authenticate(headers, body)
    except WebhookAuthError as exc:
        log.warning(
            "webhook rejected", extra={"ctx": {"account_id": account.id, "reason": str(exc)}}
        )
        raise ApiError(401, "unauthorized", "Invalid webhook signature") from None

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ApiError(400, "invalid_json", "Body is not valid JSON") from None
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_payload", "Body must be a JSON object")

    kind = provider.classify(payload)
    ignore_reason = "account disabled" if account.status == "disabled" else None
    event_id = store_event(
        db,
        provider=provider_name,
        account_id=account.id,
        payload=payload,
        raw=body,
        kind=kind,
        ignore_reason=ignore_reason,
    )
    log.info(
        "webhook received",
        extra={
            "ctx": {
                "account_id": account.id,
                "event_id": event_id,
                "kind": kind,
                "duplicate": event_id is None,
                "bytes": len(body),
            }
        },
    )
    return {"status": "duplicate" if event_id is None else "accepted"}


@router.post(
    "/webhooks/{provider_name}/{webhook_token}",
    summary="Receive provider webhook events for one WhatsApp number",
    responses={401: {}, 404: {}, 413: {}, 429: {}},
)
async def receive_webhook(
    provider_name: str,
    webhook_token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    if provider_name not in PROVIDER_NAMES:
        raise ApiError(404, "not_found", "Unknown webhook")

    if not webhook_limiter.allow(webhook_token):
        raise ApiError(429, "rate_limited", "Too many requests")

    if settings.webhook_shared_secret:
        provided = request.headers.get(settings.webhook_secret_header, "")
        if not constant_time_equals(provided, settings.webhook_shared_secret):
            raise ApiError(401, "unauthorized", "Invalid webhook credentials")

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.webhook_max_body_bytes:
        raise ApiError(413, "payload_too_large", "Payload too large")
    body = await request.body()
    if len(body) > settings.webhook_max_body_bytes:
        raise ApiError(413, "payload_too_large", "Payload too large")

    headers = {k.lower(): v for k, v in request.headers.items()}
    return await run_in_threadpool(_ingest, db, provider_name, webhook_token, headers, body)
