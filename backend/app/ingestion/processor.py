"""Canonical events → database.

Every operation here is idempotent and independent of arrival order:
- messages are inserted with ON CONFLICT DO NOTHING on (account, provider id);
  conversation counters only move when a row was actually inserted;
- statuses are stored append-only (unique per message+status) and the message's
  current status only moves "forward" (sent < delivered < read);
- statuses that arrive before their message are kept as orphans and attached
  when the message shows up;
- timestamps use LEAST/GREATEST so late events never rewind activity.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    Contact,
    Conversation,
    Message,
    MessageMedia,
    MessageStatus,
    WebhookEvent,
    WhatsAppAccount,
)
from app.phone import digits, equivalent_ids
from app.providers.base import ContactEvent, MessageEvent, ParsedChange, StatusEvent
from app.providers.registry import get_provider

log = logging.getLogger(__name__)

STATUS_RANK = {
    "received": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
    "played": 4,
    "failed": 5,
    "undeliverable": 5,
    "deleted": 6,
}


class PermanentProcessingError(Exception):
    """Retrying will not help (e.g. event belongs to a different number)."""


def process_event(db: Session, event: WebhookEvent) -> str:
    """Apply one stored webhook event. Returns the resulting event status."""
    if event.account_id is None:
        raise PermanentProcessingError("event has no account")
    account = db.get(WhatsAppAccount, event.account_id, with_for_update=False)
    if account is None:
        raise PermanentProcessingError("account no longer exists")

    changes = get_provider(event.provider).parse(event.payload)
    if not changes:
        return "ignored"

    applied = False
    for change in changes:
        _bind_account(db, account, change)
        for c in change.contacts:
            apply_contact_sync(db, c)
        for m in change.messages:
            upsert_message(db, account, m)
        for s in change.statuses:
            apply_status(db, account, s)
        for err in change.provider_errors:
            log.warning(
                "provider reported error",
                extra={"ctx": {"account_id": account.id, "event_id": event.id, "error": err}},
            )
        applied = applied or bool(change.contacts or change.messages or change.statuses)

    now = datetime.now(UTC)
    if account.status == "pending":
        account.status = "active"
    account.last_event_at = now
    return "processed" if applied else "ignored"


def _bind_account(db: Session, account: WhatsAppAccount, change: ParsedChange) -> None:
    """Make sure the event really belongs to this account (correlation guard).

    phone_number_id is authoritative. Until it is known, the display number must
    match, which catches a webhook URL registered on the wrong number.
    """
    id_confirmed = False
    if change.phone_number_id:
        if account.phone_number_id and account.phone_number_id != change.phone_number_id:
            raise PermanentProcessingError(
                f"phone_number_id mismatch: event for {change.phone_number_id}, "
                f"account {account.id} is {account.phone_number_id}"
            )
        id_confirmed = account.phone_number_id == change.phone_number_id
    display = change.display_phone_number
    if display and display != account.display_phone_number:
        if not id_confirmed:
            raise PermanentProcessingError(f"display number mismatch for account {account.id}")
        log.warning(
            "display number corrected from provider metadata",
            extra={"ctx": {"account_id": account.id}},
        )
        account.display_phone_number = display
    if change.phone_number_id and not account.phone_number_id:
        account.phone_number_id = change.phone_number_id
    if change.waba_id and not account.waba_id:
        account.waba_id = change.waba_id


# --- contacts -------------------------------------------------------------------


def get_or_create_contact(
    db: Session,
    wa_id: str,
    *,
    seen_at: datetime,
    profile_name: str | None = None,
    authoritative_id: bool = False,
) -> Contact:
    """Find the contact for a WhatsApp id, tolerating known number-format variants.

    `authoritative_id` is True when the id comes from WhatsApp itself (inbound
    `wa_id`); then an existing contact found via a variant adopts this id.
    """
    wa_id = digits(wa_id)
    if not wa_id:
        raise PermanentProcessingError("message without contact id")
    candidates = equivalent_ids(wa_id)
    contact = db.execute(
        select(Contact)
        .where(Contact.wa_id.in_(candidates))
        .order_by(Contact.wa_id != wa_id, Contact.id)
        .limit(1)
        .with_for_update()
    ).scalar_one_or_none()

    if contact is None:
        db.execute(
            insert(Contact)
            .values(
                wa_id=wa_id,
                phone=wa_id,
                name=profile_name,
                name_observed_at=seen_at if profile_name else None,
                first_seen_at=seen_at,
                last_activity_at=seen_at,
            )
            .on_conflict_do_nothing(constraint="uq_contacts_wa_id")
        )
        contact = db.execute(
            select(Contact).where(Contact.wa_id == wa_id).with_for_update()
        ).scalar_one()
    elif authoritative_id and contact.wa_id != wa_id:
        taken = db.execute(select(Contact.id).where(Contact.wa_id == wa_id)).first()
        if not taken:
            contact.wa_id = wa_id

    if profile_name and (contact.name_observed_at is None or seen_at >= contact.name_observed_at):
        contact.name = profile_name
        contact.name_observed_at = seen_at
    return contact


def apply_contact_sync(db: Session, event: ContactEvent) -> None:
    if event.action == "remove":
        return  # never delete sales history because an address-book entry went away
    seen_at = event.occurred_at or datetime.now(UTC)
    contact = get_or_create_contact(db, event.wa_id, seen_at=seen_at)
    if event.saved_name:
        contact.saved_name = event.saved_name


# --- messages -------------------------------------------------------------------


def _get_or_create_conversation(
    db: Session, account_id: int, contact_id: int, at: datetime
) -> Conversation:
    db.execute(
        insert(Conversation)
        .values(
            account_id=account_id,
            contact_id=contact_id,
            started_at=at,
            last_message_at=at,
            message_count=0,
            inbound_count=0,
            outbound_count=0,
        )
        .on_conflict_do_nothing(constraint="uq_conversations_account_contact")
    )
    return db.execute(
        select(Conversation).where(
            Conversation.account_id == account_id, Conversation.contact_id == contact_id
        )
    ).scalar_one()


def upsert_message(db: Session, account: WhatsAppAccount, m: MessageEvent) -> int | None:
    """Insert a message if new. Returns the new message id, or None for duplicates."""
    contact = get_or_create_contact(
        db,
        m.contact_wa_id,
        seen_at=m.sent_at,
        profile_name=m.contact_name if m.direction == "inbound" else None,
        authoritative_id=m.direction == "inbound" and m.source == "webhook",
    )
    conversation = _get_or_create_conversation(db, account.id, contact.id, m.sent_at)

    business = m.business_number or account.display_phone_number
    sender, recipient = (
        (contact.wa_id, business) if m.direction == "inbound" else (business, contact.wa_id)
    )
    message_id = db.execute(
        insert(Message)
        .values(
            account_id=account.id,
            conversation_id=conversation.id,
            contact_id=contact.id,
            provider_message_id=m.provider_message_id,
            direction=m.direction,
            source=m.source,
            sender=sender,
            recipient=recipient,
            type=m.type,
            text=m.text,
            content=m.content,
            context_message_id=m.context_message_id,
            sent_at=m.sent_at,
            status=m.status,
            status_at=m.sent_at if m.status else None,
            error_code=m.error_code,
            error_title=m.error_title,
        )
        .on_conflict_do_nothing(constraint="uq_messages_account_provider_id")
        .returning(Message.id)
    ).scalar_one_or_none()

    if message_id is None:
        return None  # duplicate delivery / already imported

    inbound = m.direction == "inbound"
    db.execute(
        update(Conversation)
        .where(Conversation.id == conversation.id)
        .values(
            started_at=func.least(Conversation.started_at, m.sent_at),
            last_message_at=func.greatest(Conversation.last_message_at, m.sent_at),
            last_inbound_at=func.greatest(Conversation.last_inbound_at, m.sent_at)
            if inbound
            else Conversation.last_inbound_at,
            last_outbound_at=Conversation.last_outbound_at
            if inbound
            else func.greatest(Conversation.last_outbound_at, m.sent_at),
            message_count=Conversation.message_count + 1,
            inbound_count=Conversation.inbound_count + (1 if inbound else 0),
            outbound_count=Conversation.outbound_count + (0 if inbound else 1),
        )
    )
    contact.first_seen_at = min(contact.first_seen_at, m.sent_at)
    contact.last_activity_at = max(contact.last_activity_at, m.sent_at)

    if m.source == "webhook" and inbound:
        account.last_inbound_at = _later(account.last_inbound_at, m.sent_at)
    elif m.source == "echo":
        account.last_echo_at = _later(account.last_echo_at, m.sent_at)

    if m.media is not None:
        db.execute(
            insert(MessageMedia)
            .values(
                message_id=message_id,
                account_id=account.id,
                provider_media_id=m.media.provider_media_id,
                mime_type=m.media.mime_type,
                sha256=m.media.sha256,
                filename=m.media.filename,
                download_status="pending" if m.media.provider_media_id else "skipped",
                last_error=None if m.media.provider_media_id else "no media id in payload",
            )
            .on_conflict_do_nothing(constraint="uq_message_media_message_id")
        )

    # Statuses that arrived before this message: attach and fold them in.
    orphans = db.execute(
        update(MessageStatus)
        .where(
            MessageStatus.account_id == account.id,
            MessageStatus.provider_message_id == m.provider_message_id,
            MessageStatus.message_id.is_(None),
        )
        .values(message_id=message_id)
        .returning(MessageStatus.status, MessageStatus.occurred_at)
    ).all()
    if orphans:
        msg = db.get(Message, message_id)
        assert msg is not None
        for status, occurred_at in orphans:
            _advance_status(msg, status, occurred_at)
    return message_id


def _later(a: datetime | None, b: datetime) -> datetime:
    return b if a is None or b > a else a


# --- statuses -------------------------------------------------------------------


def _advance_status(
    msg: Message,
    status: str,
    at: datetime,
    error_code: str | None = None,
    error_title: str | None = None,
) -> None:
    if STATUS_RANK.get(status, 0) > STATUS_RANK.get(msg.status or "", -1):
        msg.status = status
        msg.status_at = at
        if error_code or error_title:
            msg.error_code = error_code
            msg.error_title = error_title


def apply_status(db: Session, account: WhatsAppAccount, s: StatusEvent) -> None:
    msg = db.execute(
        select(Message)
        .where(
            Message.account_id == account.id,
            Message.provider_message_id == s.provider_message_id,
        )
        .with_for_update()
    ).scalar_one_or_none()

    inserted = db.execute(
        insert(MessageStatus)
        .values(
            account_id=account.id,
            provider_message_id=s.provider_message_id,
            message_id=msg.id if msg else None,
            status=s.status,
            occurred_at=s.occurred_at,
            recipient=s.recipient_wa_id,
            error_code=s.error_code,
            error_title=s.error_title,
            error_detail=s.error_detail,
        )
        .on_conflict_do_nothing(constraint="uq_message_statuses_account_msg_status")
        .returning(MessageStatus.id)
    ).scalar_one_or_none()

    if inserted and msg is not None:
        _advance_status(msg, s.status, s.occurred_at, s.error_code, s.error_title)
