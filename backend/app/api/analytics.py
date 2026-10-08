from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from app.api import schemas
from app.api.deps import active_cutoff, current_user
from app.api.serialize import account_ref
from app.db import get_db
from app.errors import ApiError
from app.models import Contact, Conversation, Message, WhatsAppAccount

router = APIRouter(prefix="/analytics", tags=["analytics"], dependencies=[Depends(current_user)])

MAX_RANGE_DAYS = 366


def _range(date_from: datetime | None, date_to: datetime | None) -> tuple[datetime, datetime]:
    end = date_to or datetime.now(UTC)
    start = date_from or end - timedelta(days=30)
    if start >= end:
        raise ApiError(422, "validation_error", "date_from must be before date_to")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise ApiError(422, "validation_error", f"Range is limited to {MAX_RANGE_DAYS} days")
    return start, end


# Legacy IANA names browsers still report that some PostgreSQL builds don't know.
_TZ_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Rangoon": "Asia/Yangon",
    "Europe/Kiev": "Europe/Kyiv",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
    "Pacific/Truk": "Pacific/Chuuk",
}


def _tz(db: Session, tz: str) -> str:
    """Validate against the database's own zone list (that's what will be used)."""
    for candidate in (tz, _TZ_ALIASES.get(tz)):
        if candidate and db.scalar(
            text("SELECT 1 FROM pg_timezone_names WHERE name = :n"), {"n": candidate}
        ):
            return candidate
    raise ApiError(422, "validation_error", f"Unknown timezone '{tz}'")


@router.get("/overview", response_model=schemas.Overview, summary="Headline numbers")
def overview(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account_id: int | None = Query(None, description="Limit to one WhatsApp number"),
    db: Session = Depends(get_db),
):
    start, end = _range(date_from, date_to)
    conv_where = [Conversation.account_id == account_id] if account_id else []
    msg_where = [Message.account_id == account_id] if account_id else []
    in_range = and_(Message.sent_at >= start, Message.sent_at < end)

    accounts = db.scalar(select(func.count()).select_from(WhatsAppAccount))
    if account_id:
        contacts = db.scalar(
            select(func.count(func.distinct(Conversation.contact_id))).where(*conv_where)
        )
        new_contacts = db.scalar(
            select(func.count(func.distinct(Conversation.contact_id)))
            .join(Contact, Contact.id == Conversation.contact_id)
            .where(*conv_where, Contact.first_seen_at >= start, Contact.first_seen_at < end)
        )
    else:
        contacts = db.scalar(select(func.count()).select_from(Contact))
        new_contacts = db.scalar(
            select(func.count()).where(Contact.first_seen_at >= start, Contact.first_seen_at < end)
        )

    conv_total, conv_active = db.execute(
        select(
            func.count(), func.count().filter(Conversation.last_message_at >= active_cutoff())
        ).where(*conv_where)
    ).one()

    inbound = Message.direction == "inbound"
    msg_total, inbound_n, outbound_n, conv_in_range = db.execute(
        select(
            func.count(),
            func.count().filter(and_(in_range, inbound)),
            func.count().filter(and_(in_range, ~inbound)),
            func.count(func.distinct(Message.conversation_id)).filter(in_range),
        ).where(*msg_where)
    ).one()

    per_account = {
        row[0]: row[1:]
        for row in db.execute(
            select(
                Message.account_id,
                func.count().filter(inbound),
                func.count().filter(~inbound),
                func.count(func.distinct(Message.conversation_id)),
            )
            .where(in_range, *msg_where)
            .group_by(Message.account_id)
        )
    }
    account_rows = db.execute(
        select(WhatsAppAccount)
        .where(*([WhatsAppAccount.id == account_id] if account_id else []))
        .order_by(WhatsAppAccount.name)
    ).scalars()
    by_account = [
        schemas.AccountActivity(
            account=account_ref(a),
            inbound=per_account.get(a.id, (0, 0, 0))[0],
            outbound=per_account.get(a.id, (0, 0, 0))[1],
            conversations=per_account.get(a.id, (0, 0, 0))[2],
        )
        for a in account_rows
    ]
    return schemas.Overview(
        range_from=start,
        range_to=end,
        accounts=accounts or 0,
        contacts=contacts or 0,
        conversations=conv_total,
        messages=msg_total,
        active_conversations=conv_active,
        inbound_in_range=inbound_n,
        outbound_in_range=outbound_n,
        new_contacts_in_range=new_contacts or 0,
        conversations_in_range=conv_in_range,
        by_account=by_account,
    )


_TIMESERIES_SQL = text(
    """
    WITH days AS (
        SELECT generate_series(
            date_trunc('day', CAST(:start AS timestamptz) AT TIME ZONE :tz),
            date_trunc('day', CAST(:end AS timestamptz) AT TIME ZONE :tz),
            interval '1 day'
        ) AS day
    ),
    msg AS (
        SELECT date_trunc('day', m.sent_at AT TIME ZONE :tz) AS day,
               count(*) FILTER (WHERE m.direction = 'inbound') AS inbound,
               count(*) FILTER (WHERE m.direction = 'outbound') AS outbound,
               count(DISTINCT m.conversation_id) AS conversations
        FROM messages m
        WHERE m.sent_at >= :start AND m.sent_at < :end
          AND (CAST(:account_id AS bigint) IS NULL OR m.account_id = :account_id)
        GROUP BY 1
    ),
    newc AS (
        SELECT date_trunc('day', c.first_seen_at AT TIME ZONE :tz) AS day, count(*) AS n
        FROM contacts c
        WHERE c.first_seen_at >= :start AND c.first_seen_at < :end
          AND (CAST(:account_id AS bigint) IS NULL OR EXISTS (
                SELECT 1 FROM conversations cv
                WHERE cv.contact_id = c.id AND cv.account_id = :account_id))
        GROUP BY 1
    )
    SELECT to_char(d.day, 'YYYY-MM-DD') AS date,
           coalesce(msg.inbound, 0) AS inbound,
           coalesce(msg.outbound, 0) AS outbound,
           coalesce(msg.conversations, 0) AS conversations,
           coalesce(newc.n, 0) AS new_contacts
    FROM days d
    LEFT JOIN msg ON msg.day = d.day
    LEFT JOIN newc ON newc.day = d.day
    ORDER BY d.day
    """
)


@router.get(
    "/timeseries",
    response_model=list[schemas.TimeseriesPoint],
    summary="Daily inbound/outbound messages, active conversations and new contacts",
)
def timeseries(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account_id: int | None = None,
    tz: str = Query("UTC", description="IANA timezone for day boundaries, e.g. Asia/Kolkata"),
    db: Session = Depends(get_db),
):
    start, end = _range(date_from, date_to)
    rows = db.execute(
        _TIMESERIES_SQL,
        {"start": start, "end": end, "tz": _tz(db, tz), "account_id": account_id},
    ).mappings()
    return [schemas.TimeseriesPoint(**r) for r in rows]
