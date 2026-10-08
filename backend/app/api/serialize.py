"""ORM → API schema helpers shared by routers."""

from datetime import datetime

from app.api import schemas
from app.models import Contact, Conversation, Message, WhatsAppAccount
from app.phone import format_display


def account_ref(a: WhatsAppAccount) -> schemas.AccountRef:
    return schemas.AccountRef(id=a.id, name=a.name, display_phone_number=a.display_phone_number)


def contact_display_name(c: Contact) -> str:
    return c.saved_name or c.name or format_display(c.wa_id) or c.wa_id


def contact_ref(c: Contact) -> schemas.ContactRef:
    return schemas.ContactRef(
        id=c.id,
        wa_id=c.wa_id,
        phone=format_display(c.phone or c.wa_id),
        display_name=contact_display_name(c),
    )


def conversation_out(
    c: Conversation, active_cutoff: datetime, last: Message | None = None
) -> schemas.ConversationOut:
    return schemas.ConversationOut(
        id=c.id,
        account=account_ref(c.account),
        contact=contact_ref(c.contact),
        status="active" if c.last_message_at >= active_cutoff else "inactive",
        started_at=c.started_at,
        last_message_at=c.last_message_at,
        last_inbound_at=c.last_inbound_at,
        last_outbound_at=c.last_outbound_at,
        message_count=c.message_count,
        inbound_count=c.inbound_count,
        outbound_count=c.outbound_count,
        assigned_agent=c.assigned_agent,
        last_message=schemas.MessagePreview(
            type=last.type, text=last.text, direction=last.direction, sent_at=last.sent_at
        )
        if last
        else None,
    )


def message_out(m: Message, with_statuses: list | None = None) -> schemas.MessageOut:
    media = m.media
    return schemas.MessageOut(
        id=m.id,
        conversation_id=m.conversation_id,
        account_id=m.account_id,
        contact_id=m.contact_id,
        provider_message_id=m.provider_message_id,
        direction=m.direction,
        source=m.source,
        sender=m.sender,
        recipient=m.recipient,
        type=m.type,
        text=m.text,
        content=m.content or {},
        context_message_id=m.context_message_id,
        sent_at=m.sent_at,
        status=m.status,
        status_at=m.status_at,
        error_code=m.error_code,
        error_title=m.error_title,
        media=schemas.MediaOut(
            id=media.id,
            mime_type=media.mime_type,
            filename=media.filename,
            size_bytes=media.size_bytes,
            download_status=media.download_status,
            available=media.download_status == "downloaded" and bool(media.storage_key),
        )
        if media
        else None,
        statuses=[schemas.StatusOut.model_validate(s) for s in with_statuses]
        if with_statuses is not None
        else None,
    )
