"""360dialog (WhatsApp Cloud API) webhook payload → canonical events.

Two envelope formats are accepted:

1. Meta Cloud API format (live messages, statuses, echoes):
   {"object": "whatsapp_business_account",
    "entry": [{"id": WABA_ID, "changes": [{"field": "...", "value": {...}}]}]}

2. 360dialog wrapped event format used in the coexistence docs:
   {"id": "...", "event": "history" | "smb_app_state_sync" | ..., "data": {...}}

Fields handled: messages (inbound + statuses), smb_message_echoes (messages sent
from the WhatsApp Business App), history (coexistence history sync) and
smb_app_state_sync (Business App address book). Anything else is ignored.
"""

from datetime import UTC, datetime
from typing import Any

from app.phone import digits
from app.providers.base import (
    ContactEvent,
    MediaRef,
    MessageEvent,
    ParsedChange,
    StatusEvent,
)

MEDIA_TYPES = {"image", "video", "audio", "document", "sticker"}
HANDLED_FIELDS = {"messages", "smb_message_echoes", "history", "smb_app_state_sync"}

# history_context.status values (upper-case in Meta's payloads) → our status names.
_HISTORY_STATUS = {
    "PENDING": "sent",
    "SENT": "sent",
    "DELIVERED": "delivered",
    "READ": "read",
    "PLAYED": "played",
    "ERROR": "failed",
}


def _ts(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


# --- envelope -----------------------------------------------------------------


def _changes(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any], str | None]]:
    """Return (field, value, waba_id) for each change in either envelope format."""
    if payload.get("object") == "whatsapp_business_account" and isinstance(
        payload.get("entry"), list
    ):
        out = []
        for entry in payload["entry"]:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes") or []:
                if isinstance(change, dict) and isinstance(change.get("value"), dict):
                    out.append((str(change.get("field")), change["value"], _str(entry.get("id"))))
        return out
    if isinstance(payload.get("event"), str) and isinstance(payload.get("data"), dict):
        data = payload["data"]
        return [(payload["event"], data, _str(data.get("id")))]
    return []


def classify(payload: dict[str, Any]) -> str | None:
    changes = _changes(payload)
    if not changes:
        return None
    kinds = []
    for field_name, value, _ in changes:
        if field_name == "messages":
            if value.get("messages"):
                kinds.append("messages")
            if value.get("statuses"):
                kinds.append("statuses")
            if not value.get("messages") and not value.get("statuses"):
                kinds.append("messages")
        else:
            kinds.append(field_name)
    return ",".join(sorted(set(kinds)))[:64]


def parse(payload: dict[str, Any]) -> list[ParsedChange]:
    results = []
    for field_name, value, waba_id in _changes(payload):
        metadata = value.get("metadata") or {}
        change = ParsedChange(
            kind=field_name,
            phone_number_id=_str(metadata.get("phone_number_id")),
            display_phone_number=digits(metadata.get("display_phone_number")) or None,
            waba_id=waba_id,
        )
        if field_name == "messages":
            _parse_messages(value, change)
        elif field_name == "smb_message_echoes":
            _parse_echoes(value, change)
        elif field_name == "history":
            _parse_history(value, change)
        elif field_name == "smb_app_state_sync":
            _parse_state_sync(value, change)
        for err in value.get("errors") or []:
            change.provider_errors.append(_error_text(err))
        results.append(change)
    return results


# --- per field ----------------------------------------------------------------


def _parse_messages(value: dict[str, Any], change: ParsedChange) -> None:
    names = {
        digits(c.get("wa_id")): (c.get("profile") or {}).get("name")
        for c in value.get("contacts") or []
        if isinstance(c, dict)
    }
    business = change.display_phone_number or ""
    for msg in value.get("messages") or []:
        if not isinstance(msg, dict) or not msg.get("id"):
            continue
        sender = digits(msg.get("from"))
        change.messages.append(
            _message(
                msg,
                direction="inbound",
                source="webhook",
                contact=sender,
                business=business,
                contact_name=names.get(sender),
                status="received",
            )
        )
    for st in value.get("statuses") or []:
        if not isinstance(st, dict) or not st.get("id") or not st.get("status"):
            continue
        errors = st.get("errors") or []
        first = errors[0] if errors and isinstance(errors[0], dict) else {}
        change.statuses.append(
            StatusEvent(
                provider_message_id=str(st["id"]),
                status=str(st["status"]).lower(),
                occurred_at=_ts(st.get("timestamp")),
                recipient_wa_id=digits(st.get("recipient_id")) or None,
                error_code=_str(first.get("code")),
                error_title=_str(first.get("title") or first.get("message")),
                error_detail=_str((first.get("error_data") or {}).get("details")),
            )
        )


def _parse_echoes(value: dict[str, Any], change: ParsedChange) -> None:
    business = change.display_phone_number or ""
    for msg in value.get("message_echoes") or []:
        if not isinstance(msg, dict) or not msg.get("id"):
            continue
        change.messages.append(
            _message(
                msg,
                direction="outbound",
                source="echo",
                contact=digits(msg.get("to")),
                business=digits(msg.get("from")) or business,
            )
        )


def _parse_history(value: dict[str, Any], change: ParsedChange) -> None:
    business = change.display_phone_number or ""
    for chunk in value.get("history") or []:
        if not isinstance(chunk, dict):
            continue
        for err in chunk.get("errors") or []:
            change.provider_errors.append(_error_text(err))
        for thread in chunk.get("threads") or []:
            if not isinstance(thread, dict):
                continue
            contact = digits(thread.get("id"))
            for msg in thread.get("messages") or []:
                if not isinstance(msg, dict) or not msg.get("id"):
                    continue
                sender = digits(msg.get("from"))
                outbound = bool(business) and sender == business
                if not outbound and not business and contact and sender and sender != contact:
                    outbound = True
                hist_status = str((msg.get("history_context") or {}).get("status") or "").upper()
                change.messages.append(
                    _message(
                        msg,
                        direction="outbound" if outbound else "inbound",
                        source="history",
                        contact=contact or (digits(msg.get("to")) if outbound else sender),
                        business=business or (sender if outbound else digits(msg.get("to"))),
                        status=_HISTORY_STATUS.get(hist_status) if outbound else "received",
                    )
                )


def _parse_state_sync(value: dict[str, Any], change: ParsedChange) -> None:
    for item in value.get("state_sync") or []:
        if not isinstance(item, dict) or item.get("type") != "contact":
            continue
        contact = item.get("contact") or {}
        wa_id = digits(contact.get("phone_number"))
        if not wa_id:
            continue
        change.contacts.append(
            ContactEvent(
                wa_id=wa_id,
                saved_name=_str(contact.get("full_name") or contact.get("first_name")),
                action=str(item.get("action") or "add"),
                occurred_at=_ts((item.get("metadata") or {}).get("timestamp"))
                if (item.get("metadata") or {}).get("timestamp")
                else None,
            )
        )


# --- message content ------------------------------------------------------------


def _message(
    msg: dict[str, Any],
    *,
    direction: str,
    source: str,
    contact: str,
    business: str,
    contact_name: str | None = None,
    status: str | None = None,
) -> MessageEvent:
    msg_type = str(msg.get("type") or "unknown")
    text, content, media = _content(msg_type, msg)
    context = msg.get("context") or {}
    error = (msg.get("errors") or [{}])[0] if msg.get("errors") else {}
    return MessageEvent(
        provider_message_id=str(msg["id"]),
        direction=direction,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        contact_wa_id=contact,
        business_number=business,
        sent_at=_ts(msg.get("timestamp")),
        type=msg_type,
        text=text,
        content=content,
        media=media,
        context_message_id=_str(context.get("id")),
        contact_name=_str(contact_name),
        status=status,
        error_code=_str(error.get("code")) if isinstance(error, dict) else None,
        error_title=_str(error.get("title")) if isinstance(error, dict) else None,
    )


def _content(msg_type: str, msg: dict[str, Any]) -> tuple[str | None, dict[str, Any], MediaRef | None]:
    body = msg.get(msg_type)
    obj: dict[str, Any] = body if isinstance(body, dict) else {}

    if msg_type == "text":
        return _str(obj.get("body")), {}, None

    if msg_type in MEDIA_TYPES:
        media = MediaRef(
            provider_media_id=_str(obj.get("id")),
            mime_type=_str(obj.get("mime_type")),
            sha256=_str(obj.get("sha256")),
            filename=_str(obj.get("filename")),
            caption=_str(obj.get("caption")),
        )
        extra = {k: obj[k] for k in ("voice", "animated") if k in obj}
        return media.caption, extra, media

    if msg_type == "location":
        text = " — ".join(p for p in (obj.get("name"), obj.get("address")) if p) or None
        return text, obj, None

    if msg_type == "contacts":
        cards = body if isinstance(body, list) else []
        names = [((c.get("name") or {}).get("formatted_name")) for c in cards if isinstance(c, dict)]
        names = [n for n in names if n]
        return (", ".join(names) or None), {"contacts": cards}, None

    if msg_type == "interactive":
        kind = obj.get("type")
        reply = obj.get(kind) if isinstance(kind, str) and isinstance(obj.get(kind), dict) else {}
        text = reply.get("title") or reply.get("body") or reply.get("name")
        return _str(text), obj, None

    if msg_type == "button":
        return _str(obj.get("text")), obj, None

    if msg_type == "reaction":
        return _str(obj.get("emoji")), obj, None

    if msg_type == "order":
        return _str(obj.get("text")), obj, None

    if msg_type == "system":
        return _str(obj.get("body")), obj, None

    if msg_type == "template":
        return _str(obj.get("name")), obj, None

    # unsupported / unknown types: keep whatever the provider sent for this type.
    return None, obj, None


def _error_text(err: Any) -> str:
    if not isinstance(err, dict):
        return str(err)[:500]
    return f"{err.get('code', '?')}: {err.get('title') or err.get('message') or 'error'}"[:500]
