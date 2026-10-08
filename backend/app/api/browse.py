"""Read-only browsing of contacts, conversations and messages."""

import re
from collections import defaultdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.api import schemas
from app.api.deps import Page, active_cutoff, current_user, pagination, parse_sort
from app.api.serialize import (
    account_ref,
    contact_display_name,
    conversation_out,
    message_out,
)
from app.db import get_db
from app.errors import ApiError, not_found
from app.media.storage import get_storage
from app.models import (
    Contact,
    Conversation,
    Message,
    MessageMedia,
    MessageStatus,
    User,
    WhatsAppAccount,
)
from app.phone import format_display

router = APIRouter(dependencies=[Depends(current_user)])


def like(q: str) -> str:
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# Must match the expression of the ix_contacts_search_trgm index.
_CONTACT_SEARCH = (
    func.coalesce(Contact.name, "")
    + literal(" ")
    + func.coalesce(Contact.saved_name, "")
    + literal(" ")
    + Contact.wa_id
)


def _contact_search(q: str):
    digits_only = re.sub(r"\D", "", q)
    clauses = [_CONTACT_SEARCH.ilike(like(q))]
    if len(digits_only) >= 4 and digits_only != q.strip():
        clauses.append(Contact.wa_id.like(like(digits_only)))
    return or_(*clauses)


def _count(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


# --- contacts -------------------------------------------------------------------

CONTACT_SORTS = {
    "last_activity_at": Contact.last_activity_at,
    "first_seen_at": Contact.first_seen_at,
    "name": func.coalesce(Contact.saved_name, Contact.name, Contact.wa_id),
}


def _contacts_out(db: Session, contacts: list[Contact]) -> list[schemas.ContactOut]:
    ids = [c.id for c in contacts]
    per: dict[int, dict] = defaultdict(lambda: {"conversations": 0, "messages": 0, "accounts": []})
    if ids:
        rows = db.execute(
            select(Conversation.contact_id, Conversation.message_count, WhatsAppAccount)
            .join(WhatsAppAccount, WhatsAppAccount.id == Conversation.account_id)
            .where(Conversation.contact_id.in_(ids))
            .order_by(WhatsAppAccount.name)
        ).all()
        for contact_id, message_count, account in rows:
            p = per[contact_id]
            p["conversations"] += 1
            p["messages"] += message_count
            p["accounts"].append(account_ref(account))
    return [
        schemas.ContactOut(
            id=c.id,
            wa_id=c.wa_id,
            phone=format_display(c.phone or c.wa_id),
            display_name=contact_display_name(c),
            name=c.name,
            saved_name=c.saved_name,
            first_seen_at=c.first_seen_at,
            last_activity_at=c.last_activity_at,
            **per[c.id],
        )
        for c in contacts
    ]


@router.get("/contacts", response_model=schemas.Paginated[schemas.ContactOut], tags=["contacts"])
def list_contacts(
    q: str | None = Query(None, max_length=100, description="Name or phone number"),
    account_id: int | None = Query(None, description="Only contacts who talked to this number"),
    active_from: datetime | None = Query(None, description="Last activity at or after"),
    active_to: datetime | None = Query(None, description="Last activity before"),
    sort: str | None = Query(None, description="e.g. -last_activity_at, name"),
    page: Page = Depends(pagination),
    db: Session = Depends(get_db),
):
    stmt = select(Contact)
    if q:
        stmt = stmt.where(_contact_search(q))
    if account_id is not None:
        stmt = stmt.where(
            exists().where(
                Conversation.contact_id == Contact.id, Conversation.account_id == account_id
            )
        )
    if active_from:
        stmt = stmt.where(Contact.last_activity_at >= active_from)
    if active_to:
        stmt = stmt.where(Contact.last_activity_at < active_to)
    total = _count(db, stmt)
    order = parse_sort(sort, CONTACT_SORTS, "-last_activity_at")
    contacts = (
        db.execute(stmt.order_by(order, Contact.id.desc()).limit(page.limit).offset(page.offset))
        .scalars()
        .all()
    )
    return schemas.Paginated(
        items=_contacts_out(db, list(contacts)), total=total, limit=page.limit, offset=page.offset
    )


@router.get("/contacts/{contact_id}", response_model=schemas.ContactOut, tags=["contacts"])
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    c = db.get(Contact, contact_id)
    if c is None:
        raise not_found("Contact")
    return _contacts_out(db, [c])[0]


# --- conversations --------------------------------------------------------------

CONVERSATION_SORTS = {
    "last_message_at": Conversation.last_message_at,
    "started_at": Conversation.started_at,
    "message_count": Conversation.message_count,
}


def _last_messages(db: Session, conversation_ids: list[int]) -> dict[int, Message]:
    if not conversation_ids:
        return {}
    rows = (
        db.execute(
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .ext(distinct_on(Message.conversation_id))
            .order_by(Message.conversation_id, Message.sent_at.desc(), Message.id.desc())
        )
        .scalars()
        .all()
    )
    return {m.conversation_id: m for m in rows}


@router.get(
    "/conversations",
    response_model=schemas.Paginated[schemas.ConversationOut],
    tags=["conversations"],
)
def list_conversations(
    account_id: list[int] | None = Query(None, description="One or more WhatsApp numbers"),
    contact_id: int | None = None,
    q: str | None = Query(None, max_length=100, description="Contact name or phone"),
    status: Literal["active", "inactive"] | None = None,
    date_from: datetime | None = Query(None, description="Had activity at or after"),
    date_to: datetime | None = Query(None, description="Had activity before"),
    agent: str | None = Query(None, max_length=200),
    sort: str | None = Query(None, description="e.g. -last_message_at, -message_count"),
    page: Page = Depends(pagination),
    db: Session = Depends(get_db),
):
    stmt = select(Conversation).join(Contact, Contact.id == Conversation.contact_id)
    if account_id:
        stmt = stmt.where(Conversation.account_id.in_(account_id))
    if contact_id is not None:
        stmt = stmt.where(Conversation.contact_id == contact_id)
    if q:
        stmt = stmt.where(_contact_search(q))
    cutoff = active_cutoff()
    if status == "active":
        stmt = stmt.where(Conversation.last_message_at >= cutoff)
    elif status == "inactive":
        stmt = stmt.where(Conversation.last_message_at < cutoff)
    if date_from:
        stmt = stmt.where(Conversation.last_message_at >= date_from)
    if date_to:
        stmt = stmt.where(Conversation.started_at < date_to)
    if agent:
        stmt = stmt.where(Conversation.assigned_agent.ilike(like(agent)))

    total = _count(db, stmt)
    order = parse_sort(sort, CONVERSATION_SORTS, "-last_message_at")
    rows = (
        db.execute(
            stmt.order_by(order, Conversation.id.desc()).limit(page.limit).offset(page.offset)
        )
        .unique()
        .scalars()
        .all()
    )
    last = _last_messages(db, [c.id for c in rows])
    return schemas.Paginated(
        items=[conversation_out(c, cutoff, last.get(c.id)) for c in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


def _get_conversation(db: Session, conversation_id: int) -> Conversation:
    c = db.get(Conversation, conversation_id)
    if c is None:
        raise not_found("Conversation")
    return c


@router.get(
    "/conversations/{conversation_id}",
    response_model=schemas.ConversationOut,
    tags=["conversations"],
)
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    c = _get_conversation(db, conversation_id)
    return conversation_out(c, active_cutoff(), _last_messages(db, [c.id]).get(c.id))


def _statuses_for(db: Session, message_ids: list[int]) -> dict[int, list[MessageStatus]]:
    out: dict[int, list[MessageStatus]] = defaultdict(list)
    if message_ids:
        for s in db.execute(
            select(MessageStatus)
            .where(MessageStatus.message_id.in_(message_ids))
            .order_by(MessageStatus.occurred_at)
        ).scalars():
            out[s.message_id].append(s)
    return out


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=schemas.Paginated[schemas.MessageOut],
    tags=["conversations"],
    summary="Message timeline (oldest first by default)",
)
def conversation_messages(
    conversation_id: int,
    order: Literal["asc", "desc"] = "asc",
    page: Page = Depends(pagination),
    db: Session = Depends(get_db),
):
    _get_conversation(db, conversation_id)
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    total = _count(db, stmt)
    sort = (
        (Message.sent_at.asc(), Message.id.asc())
        if order == "asc"
        else (
            Message.sent_at.desc(),
            Message.id.desc(),
        )
    )
    msgs = db.execute(stmt.order_by(*sort).limit(page.limit).offset(page.offset)).scalars().all()
    statuses = _statuses_for(db, [m.id for m in msgs])
    return schemas.Paginated(
        items=[message_out(m, statuses.get(m.id, [])) for m in msgs],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# --- messages -------------------------------------------------------------------


@router.get("/messages", response_model=schemas.Paginated[schemas.MessageOut], tags=["messages"])
def list_messages(
    account_id: int | None = None,
    conversation_id: int | None = None,
    contact_id: int | None = None,
    direction: Literal["inbound", "outbound"] | None = None,
    type: str | None = Query(None, max_length=32),
    status: str | None = Query(None, max_length=16),
    source: Literal["webhook", "echo", "history"] | None = None,
    q: str | None = Query(None, max_length=200, description="Search message text"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: Literal["sent_at", "-sent_at"] = "-sent_at",
    page: Page = Depends(pagination),
    db: Session = Depends(get_db),
):
    stmt = select(Message)
    for col, val in (
        (Message.account_id, account_id),
        (Message.conversation_id, conversation_id),
        (Message.contact_id, contact_id),
        (Message.direction, direction),
        (Message.type, type),
        (Message.status, status),
        (Message.source, source),
    ):
        if val is not None:
            stmt = stmt.where(col == val)
    if q:
        stmt = stmt.where(Message.text.ilike(like(q)))
    if date_from:
        stmt = stmt.where(Message.sent_at >= date_from)
    if date_to:
        stmt = stmt.where(Message.sent_at < date_to)
    total = _count(db, stmt)
    order = Message.sent_at.desc() if sort == "-sent_at" else Message.sent_at.asc()
    msgs = (
        db.execute(stmt.order_by(order, Message.id).limit(page.limit).offset(page.offset))
        .scalars()
        .all()
    )
    return schemas.Paginated(
        items=[message_out(m) for m in msgs], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/messages/{message_id}", response_model=schemas.MessageOut, tags=["messages"])
def get_message(message_id: int, db: Session = Depends(get_db)):
    m = db.get(Message, message_id)
    if m is None:
        raise not_found("Message")
    return message_out(m, _statuses_for(db, [m.id]).get(m.id, []))


_INLINE_TYPES = ("image/", "video/", "audio/", "application/pdf")


@router.get(
    "/messages/{message_id}/media",
    tags=["messages"],
    summary="Download the message's media file",
    response_class=Response,
)
def get_message_media(
    message_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)
):
    media = db.execute(
        select(MessageMedia).where(MessageMedia.message_id == message_id)
    ).scalar_one_or_none()
    if media is None:
        raise not_found("Media")
    if media.download_status != "downloaded" or not media.storage_key:
        raise ApiError(409, "media_unavailable", f"Media is {media.download_status}")
    data, stored_type = get_storage().get(media.storage_key)
    mime = media.mime_type or stored_type or "application/octet-stream"
    disposition = "inline" if mime.startswith(_INLINE_TYPES) else "attachment"
    filename = re.sub(r"[^\w.\- ]", "_", media.filename or f"media-{media.id}")[:120]
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )
