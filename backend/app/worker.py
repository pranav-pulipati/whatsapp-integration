"""Background worker: processes queued webhook events and downloads media.

Run with `python -m app.worker`. Several workers can run concurrently: rows are
claimed with SELECT ... FOR UPDATE SKIP LOCKED, and a claim is held by the
transaction itself, so a crashed worker simply releases its row.
"""

import logging
import signal
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope
from app.ingestion.processor import PermanentProcessingError, process_event
from app.logging_setup import configure_logging, redact
from app.media.storage import Storage, get_storage
from app.models import MessageMedia, WebhookEvent, WhatsAppAccount
from app.providers.base import ProviderError
from app.providers.registry import get_provider
from app.security import decrypt_secret

log = logging.getLogger("app.worker")


def backoff(attempt: int, base_seconds: int = 30, cap_seconds: int = 3600) -> timedelta:
    return timedelta(seconds=min(cap_seconds, base_seconds * 2 ** max(0, attempt - 1)))


def _error_text(exc: BaseException) -> str:
    return redact(f"{type(exc).__name__}: {exc}")[:1000]


# --- webhook events -------------------------------------------------------------


def process_next_event(db: Session) -> bool:
    """Claim and process one due event in the current transaction.
    Returns False when the queue is empty."""
    settings = get_settings()
    event = db.execute(
        select(WebhookEvent)
        .where(
            WebhookEvent.status.in_(("pending", "retry")),
            WebhookEvent.next_attempt_at <= datetime.now(UTC),
        )
        .order_by(WebhookEvent.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if event is None:
        return False

    event.attempts += 1
    ctx = {"event_id": event.id, "account_id": event.account_id, "kind": event.event_kind}
    try:
        with db.begin_nested():
            result = process_event(db, event)
        event.status = result
        event.processed_at = datetime.now(UTC)
        event.last_error = None
        log.info("event processed", extra={"ctx": {**ctx, "result": result}})
    except PermanentProcessingError as exc:
        event.status = "dead"
        event.last_error = _error_text(exc)
        log.error("event rejected", extra={"ctx": {**ctx, "error": event.last_error}})
    except Exception as exc:
        event.last_error = _error_text(exc)
        if event.attempts >= settings.event_max_attempts:
            event.status = "dead"
            log.exception("event dead after max attempts", extra={"ctx": ctx})
        else:
            event.status = "retry"
            event.next_attempt_at = datetime.now(UTC) + backoff(event.attempts)
            log.warning(
                "event failed, will retry",
                extra={"ctx": {**ctx, "attempt": event.attempts, "error": event.last_error}},
            )
    return True


# --- media ----------------------------------------------------------------------


_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/aac": "aac",
    "application/pdf": "pdf",
}


def media_storage_key(media: MessageMedia, mime_type: str | None) -> str:
    ext = _EXT.get((mime_type or "").split(";")[0].strip(), "bin")
    return f"media/{media.account_id}/{media.message_id}/{media.id}.{ext}"


def process_next_media(db: Session, storage: Storage | None = None) -> bool:
    settings = get_settings()
    media = db.execute(
        select(MessageMedia)
        .where(
            MessageMedia.download_status == "pending",
            MessageMedia.next_attempt_at <= datetime.now(UTC),
        )
        .order_by(MessageMedia.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if media is None:
        return False

    account = db.get(WhatsAppAccount, media.account_id)
    media.attempts += 1
    ctx = {"media_id": media.id, "message_id": media.message_id, "account_id": media.account_id}
    try:
        if account is None or not account.api_key_encrypted:
            raise ProviderError("no API key configured for this number")
        fetched = get_provider(account.provider).fetch_media(
            decrypt_secret(account.api_key_encrypted), media.provider_media_id or ""
        )
        mime = media.mime_type or fetched.mime_type
        key = media_storage_key(media, mime)
        (storage or get_storage()).put(key, fetched.content, mime)
        media.storage_key = key
        media.size_bytes = len(fetched.content)
        media.mime_type = mime
        media.download_status = "downloaded"
        media.downloaded_at = datetime.now(UTC)
        media.last_error = None
        log.info("media stored", extra={"ctx": {**ctx, "bytes": media.size_bytes}})
    except Exception as exc:
        media.last_error = _error_text(exc)
        retryable = not isinstance(exc, ProviderError) or exc.retryable
        if not retryable or media.attempts >= settings.media_max_attempts:
            media.download_status = "failed"
            log.error("media download failed", extra={"ctx": {**ctx, "error": media.last_error}})
        else:
            media.next_attempt_at = datetime.now(UTC) + backoff(media.attempts, base_seconds=60)
            log.warning(
                "media download will retry", extra={"ctx": {**ctx, "error": media.last_error}}
            )
    return True


# --- housekeeping ---------------------------------------------------------------


def purge_old_events(db: Session) -> int:
    """Delete raw payloads (PII) of successfully handled events after retention."""
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().raw_event_retention_days)
    result = db.execute(
        delete(WebhookEvent).where(
            WebhookEvent.status.in_(("processed", "ignored")),
            WebhookEvent.received_at < cutoff,
        )
    )
    return result.rowcount or 0


# --- loop -----------------------------------------------------------------------


def drain(max_items: int = 10_000, storage: Storage | None = None) -> int:
    """Process everything currently due (used by tests and the CLI)."""
    done = 0
    while done < max_items:
        with session_scope() as db:
            worked = process_next_event(db)
        if not worked:
            break
        done += 1
    while done < max_items:
        with session_scope() as db:
            worked = process_next_media(db, storage)
        if not worked:
            break
        done += 1
    return done


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.validate_for_runtime()
    stopping = False

    def _stop(*_: object) -> None:
        nonlocal stopping
        stopping = True
        log.info("worker stopping")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        storage = get_storage()
        if hasattr(storage, "ensure_bucket"):
            storage.ensure_bucket()
    except Exception as exc:
        log.warning("could not verify media bucket", extra={"ctx": {"error": _error_text(exc)}})
    log.info("worker started")
    last_purge = 0.0

    while not stopping:
        busy = False
        try:
            for _ in range(100):
                with session_scope() as db:
                    if not process_next_event(db):
                        break
                busy = True
                if stopping:
                    break
            for _ in range(10):
                with session_scope() as db:
                    if not process_next_media(db):
                        break
                busy = True
                if stopping:
                    break
            if time.monotonic() - last_purge > 600:
                with session_scope() as db:
                    purged = purge_old_events(db)
                if purged:
                    log.info("purged old raw events", extra={"ctx": {"count": purged}})
                last_purge = time.monotonic()
        except Exception:
            log.exception("worker loop error")
            time.sleep(5)
        if not busy:
            time.sleep(settings.worker_poll_interval_seconds)


if __name__ == "__main__":
    run()
