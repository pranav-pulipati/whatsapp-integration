"""Operational endpoints: inspect and replay failed events / media (admin only)."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api import schemas
from app.api.deps import Page, pagination, require_admin
from app.db import get_db
from app.errors import not_found
from app.models import MessageMedia, WebhookEvent

router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(require_admin)])


@router.get("/webhook-events", response_model=schemas.Paginated[schemas.WebhookEventOut])
def list_events(
    status: Literal["pending", "retry", "processed", "ignored", "dead"] | None = None,
    account_id: int | None = None,
    page: Page = Depends(pagination),
    db: Session = Depends(get_db),
):
    stmt = select(WebhookEvent)
    if status:
        stmt = stmt.where(WebhookEvent.status == status)
    if account_id is not None:
        stmt = stmt.where(WebhookEvent.account_id == account_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(WebhookEvent.id.desc()).limit(page.limit).offset(page.offset)
    ).scalars()
    return schemas.Paginated(
        items=[schemas.WebhookEventOut.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/summary", summary="Queue health")
def summary(db: Session = Depends(get_db)) -> dict:
    events = dict(
        db.execute(select(WebhookEvent.status, func.count()).group_by(WebhookEvent.status)).all()
    )
    media = dict(
        db.execute(
            select(MessageMedia.download_status, func.count()).group_by(
                MessageMedia.download_status
            )
        ).all()
    )
    oldest_pending = db.scalar(
        select(func.min(WebhookEvent.received_at)).where(
            WebhookEvent.status.in_(("pending", "retry"))
        )
    )
    return {"events": events, "media": media, "oldest_pending_event_at": oldest_pending}


@router.post("/webhook-events/{event_id}/retry", response_model=schemas.WebhookEventOut)
def retry_event(event_id: int, db: Session = Depends(get_db)):
    ev = db.get(WebhookEvent, event_id)
    if ev is None:
        raise not_found("Event")
    ev.status, ev.attempts, ev.next_attempt_at = "pending", 0, datetime.now(UTC)
    db.commit()
    db.refresh(ev)
    return schemas.WebhookEventOut.model_validate(ev)


@router.post("/retry-failed", summary="Requeue all dead events and failed media downloads")
def retry_failed(
    include_media: bool = Query(True), db: Session = Depends(get_db)
) -> dict[str, int]:
    now = datetime.now(UTC)
    events = db.execute(
        update(WebhookEvent)
        .where(WebhookEvent.status == "dead")
        .values(status="pending", attempts=0, next_attempt_at=now)
    ).rowcount
    media = 0
    if include_media:
        media = db.execute(
            update(MessageMedia)
            .where(MessageMedia.download_status == "failed")
            .values(download_status="pending", attempts=0, next_attempt_at=now)
        ).rowcount
    db.commit()
    return {"events": events or 0, "media": media or 0}
