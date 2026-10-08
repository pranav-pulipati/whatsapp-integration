"""WhatsApp numbers: listing with stats + capture health, and onboarding.

Adding a number is a POST here (or `python -m app.cli add-account`); no code or
configuration changes are needed.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import active_cutoff, current_user, require_admin
from app.api.schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    ApiKeyUpdate,
    CaptureHealth,
    WebhookInfo,
)
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError, not_found
from app.models import Conversation, Message, MessageStatus, User, WebhookEvent, WhatsAppAccount
from app.providers.base import ProviderError
from app.providers.registry import get_provider
from app.security import decrypt_secret, encrypt_secret, generate_webhook_token

log = logging.getLogger(__name__)
router = APIRouter(prefix="/accounts", tags=["accounts"])

# Statuses younger than this may simply be waiting for their echo to be processed.
ORPHAN_GRACE = timedelta(minutes=10)
STALE_AFTER = timedelta(days=3)


def webhook_url(account: WhatsAppAccount) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/webhooks/{account.provider}/{account.webhook_token}"


def _stats(db: Session, account_ids: list[int]) -> dict[int, dict]:
    if not account_ids:
        return {}
    now = datetime.now(UTC)
    week = now - timedelta(days=7)
    stats: dict[int, dict] = {i: {} for i in account_ids}

    for row in db.execute(
        select(
            Conversation.account_id,
            func.count(func.distinct(Conversation.contact_id)),
            func.count(),
            func.count().filter(Conversation.last_message_at >= active_cutoff()),
        )
        .where(Conversation.account_id.in_(account_ids))
        .group_by(Conversation.account_id)
    ):
        stats[row[0]].update(contacts=row[1], conversations=row[2], active_conversations=row[3])

    inbound = Message.direction == "inbound"
    for row in db.execute(
        select(
            Message.account_id,
            func.count(),
            func.count().filter(inbound),
            func.count().filter(~inbound),
            func.count().filter(Message.sent_at >= week),
            func.count().filter(
                and_(Message.source == "webhook", inbound, Message.sent_at >= week)
            ),
            func.count().filter(and_(Message.source == "echo", Message.sent_at >= week)),
        )
        .where(Message.account_id.in_(account_ids))
        .group_by(Message.account_id)
    ):
        stats[row[0]].update(
            messages=row[1],
            inbound_messages=row[2],
            outbound_messages=row[3],
            messages_7d=row[4],
            inbound_7d=row[5],
            echoes_7d=row[6],
        )

    for account_id, n in db.execute(
        select(MessageStatus.account_id, func.count())
        .where(
            MessageStatus.account_id.in_(account_ids),
            MessageStatus.message_id.is_(None),
            MessageStatus.created_at >= week,
            MessageStatus.created_at <= now - ORPHAN_GRACE,
        )
        .group_by(MessageStatus.account_id)
    ):
        stats[account_id]["orphan_statuses_7d"] = n

    for account_id, n in db.execute(
        select(WebhookEvent.account_id, func.count())
        .where(WebhookEvent.account_id.in_(account_ids), WebhookEvent.status == "dead")
        .group_by(WebhookEvent.account_id)
    ):
        stats[account_id]["failed_events"] = n
    return stats


def capture_health(a: WhatsAppAccount, s: dict) -> CaptureHealth:
    inbound_7d, echoes_7d = s.get("inbound_7d", 0), s.get("echoes_7d", 0)
    orphans, failed = s.get("orphan_statuses_7d", 0), s.get("failed_events", 0)
    reasons: list[str] = []
    if a.last_event_at is None:
        level = "no_data"
        reasons.append("No webhook events received yet — check the webhook registration.")
    else:
        if orphans:
            reasons.append(
                f"{orphans} delivery status(es) in the last 7 days have no matching message: "
                "some app-sent messages may not be arriving as echoes."
            )
        if inbound_7d and not echoes_7d:
            reasons.append(
                "Customers messaged in the last 7 days but no app-sent replies (echoes) arrived."
            )
        if failed:
            reasons.append(f"{failed} event(s) failed processing — see Ingestion.")
        if not a.api_key_encrypted:
            reasons.append("No 360dialog API key stored: photos, voice notes and documents can't be downloaded.")
        if datetime.now(UTC) - a.last_event_at > STALE_AFTER:
            reasons.append("No events in the last 3 days.")
        level = "warning" if reasons else "ok"
    return CaptureHealth(
        level=level,
        reasons=reasons,
        last_event_at=a.last_event_at,
        last_inbound_at=a.last_inbound_at,
        last_echo_at=a.last_echo_at,
        inbound_7d=inbound_7d,
        echoes_7d=echoes_7d,
        orphan_statuses_7d=orphans,
        failed_events=failed,
    )


def account_out(a: WhatsAppAccount, s: dict | None = None) -> AccountOut:
    s = s or {}
    return AccountOut(
        id=a.id,
        provider=a.provider,
        provider_account_id=a.provider_account_id,
        waba_id=a.waba_id,
        phone_number_id=a.phone_number_id,
        display_phone_number=a.display_phone_number,
        name=a.name,
        status=a.status,
        has_api_key=bool(a.api_key_encrypted),
        metadata=a.metadata_ or {},
        created_at=a.created_at,
        updated_at=a.updated_at,
        contacts=s.get("contacts", 0),
        conversations=s.get("conversations", 0),
        active_conversations=s.get("active_conversations", 0),
        messages=s.get("messages", 0),
        inbound_messages=s.get("inbound_messages", 0),
        outbound_messages=s.get("outbound_messages", 0),
        messages_7d=s.get("messages_7d", 0),
        health=capture_health(a, s),
    )


def _get(db: Session, account_id: int) -> WhatsAppAccount:
    a = db.get(WhatsAppAccount, account_id)
    if a is None:
        raise not_found("Account")
    return a


@router.get("", response_model=list[AccountOut], summary="All connected WhatsApp numbers")
def list_accounts(
    db: Session = Depends(get_db), _: User = Depends(current_user)
) -> list[AccountOut]:
    accounts = db.execute(select(WhatsAppAccount).order_by(WhatsAppAccount.name)).scalars().all()
    stats = _stats(db, [a.id for a in accounts])
    return [account_out(a, stats[a.id]) for a in accounts]


@router.get("/{account_id}", response_model=AccountOut)
def get_account(
    account_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)
) -> AccountOut:
    a = _get(db, account_id)
    return account_out(a, _stats(db, [a.id])[a.id])


@router.post("", response_model=AccountOut, status_code=201, summary="Onboard a WhatsApp number")
def create_account(
    body: AccountCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)
) -> AccountOut:
    a = WhatsAppAccount(
        provider=body.provider,
        provider_account_id=body.provider_account_id,
        waba_id=body.waba_id,
        phone_number_id=body.phone_number_id,
        display_phone_number=body.display_phone_number,
        name=body.name,
        status="pending",
        webhook_token=generate_webhook_token(),
        api_key_encrypted=encrypt_secret(body.api_key) if body.api_key else None,
        metadata_=body.metadata,
    )
    db.add(a)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(
            409, "conflict", "This number (or phone number id) is already connected"
        ) from None
    db.refresh(a)
    log.info("account created", extra={"ctx": {"account_id": a.id, "by_user": admin.id}})
    return account_out(a)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int,
    body: AccountUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> AccountOut:
    a = _get(db, account_id)
    data = body.model_dump(exclude_unset=True)
    if "metadata" in data:
        a.metadata_ = data.pop("metadata") or {}
    for k, v in data.items():
        setattr(a, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "conflict", "phone_number_id already used by another account") from None
    db.refresh(a)
    return account_out(a, _stats(db, [a.id])[a.id])


@router.put("/{account_id}/api-key", status_code=204, summary="Set/rotate the number's API key")
def set_api_key(
    account_id: int,
    body: ApiKeyUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> None:
    a = _get(db, account_id)
    a.api_key_encrypted = encrypt_secret(body.api_key)
    db.commit()


@router.get("/{account_id}/webhook", response_model=WebhookInfo, summary="Webhook URL (admin)")
def get_webhook(
    account_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> WebhookInfo:
    a = _get(db, account_id)
    return WebhookInfo(
        webhook_url=webhook_url(a), secret_header=get_settings().webhook_secret_header
    )


@router.post(
    "/{account_id}/register-webhook",
    response_model=WebhookInfo,
    summary="Point this number's 360dialog webhook at this service",
)
def register_webhook(
    account_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)
) -> WebhookInfo:
    settings = get_settings()
    a = _get(db, account_id)
    if not a.api_key_encrypted:
        raise ApiError(409, "missing_api_key", "Set the number's API key first")
    if not settings.webhook_shared_secret:
        raise ApiError(409, "missing_secret", "WEBHOOK_SHARED_SECRET is not configured")
    url = webhook_url(a)
    if not url.startswith("https://"):
        raise ApiError(409, "insecure_url", "PUBLIC_BASE_URL must be https:// for 360dialog")
    try:
        get_provider(a.provider).register_webhook(
            decrypt_secret(a.api_key_encrypted),
            url,
            {settings.webhook_secret_header: settings.webhook_shared_secret},
        )
    except ProviderError as exc:
        raise ApiError(502, "provider_error", str(exc)) from None
    log.info("webhook registered", extra={"ctx": {"account_id": a.id}})
    return WebhookInfo(
        webhook_url=url, secret_header=settings.webhook_secret_header, registered=True
    )
