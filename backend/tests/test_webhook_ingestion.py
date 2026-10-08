import hashlib
import hmac
import json

from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_scope
from app.models import WebhookEvent
from tests.conftest import WEBHOOK_HEADERS, make_account
from tests.helpers import fixture_bytes


def _url(account) -> str:
    return f"/webhooks/360dialog/{account.webhook_token}"


def _events():
    with session_scope() as db:
        return db.execute(select(WebhookEvent).order_by(WebhookEvent.id)).scalars().all()


def test_valid_webhook_is_persisted_and_acknowledged(client, account):
    r = client.post(_url(account), content=fixture_bytes("inbound_text"), headers=WEBHOOK_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"status": "accepted"}
    (ev,) = _events()
    assert ev.account_id == account.id
    assert ev.status == "pending"
    assert ev.event_kind == "messages"
    assert ev.source == "webhook"


def test_webhook_does_not_process_inline(client, account):
    client.post(_url(account), content=fixture_bytes("inbound_text"), headers=WEBHOOK_HEADERS)
    with session_scope() as db:
        from app.models import Message

        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_duplicate_delivery_is_stored_once(client, account):
    body = fixture_bytes("inbound_text")
    assert (
        client.post(_url(account), content=body, headers=WEBHOOK_HEADERS).json()["status"]
        == "accepted"
    )
    r = client.post(_url(account), content=body, headers=WEBHOOK_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "duplicate"
    assert len(_events()) == 1


def test_missing_or_wrong_shared_secret_is_rejected(client, account):
    body = fixture_bytes("inbound_text")
    assert client.post(_url(account), content=body).status_code == 401
    r = client.post(_url(account), content=body, headers={"X-Webhook-Secret": "nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert _events() == []


def test_unknown_token_and_provider_are_404(client, account):
    body = fixture_bytes("inbound_text")
    assert (
        client.post(
            "/webhooks/360dialog/not-a-token", content=body, headers=WEBHOOK_HEADERS
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/webhooks/other/{account.webhook_token}", content=body, headers=WEBHOOK_HEADERS
        ).status_code
        == 404
    )


def test_invalid_json_is_400(client, account):
    r = client.post(_url(account), content=b"{not json", headers=WEBHOOK_HEADERS)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_json"
    r = client.post(_url(account), content=b"[1,2]", headers=WEBHOOK_HEADERS)
    assert r.status_code == 400


def test_unrecognised_shape_is_kept_but_ignored(client, account):
    r = client.post(
        _url(account), content=json.dumps({"foo": "bar"}).encode(), headers=WEBHOOK_HEADERS
    )
    assert r.status_code == 200
    (ev,) = _events()
    assert ev.status == "ignored"
    assert ev.last_error == "unrecognised payload shape"


def test_payload_too_large(client, account, monkeypatch):
    monkeypatch.setattr(get_settings(), "webhook_max_body_bytes", 100)
    r = client.post(_url(account), content=fixture_bytes("inbound_text"), headers=WEBHOOK_HEADERS)
    assert r.status_code == 413


def test_disabled_account_events_are_kept_as_ignored(client):
    acc = make_account()
    with session_scope() as db:
        from app.models import WhatsAppAccount

        db.get(WhatsAppAccount, acc.id).status = "disabled"
    client.post(_url(acc), content=fixture_bytes("inbound_text"), headers=WEBHOOK_HEADERS)
    (ev,) = _events()
    assert ev.status == "ignored"
    assert ev.last_error == "account disabled"


def test_hmac_signature_enforced_when_required(client, account, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "dialog360_platform_secret", "platform-secret")
    monkeypatch.setattr(s, "dialog360_require_signature", True)
    body = fixture_bytes("inbound_text")
    assert client.post(_url(account), content=body, headers=WEBHOOK_HEADERS).status_code == 401
    sig = hmac.new(b"platform-secret", body, hashlib.sha256).hexdigest()
    r = client.post(
        _url(account), content=body, headers={**WEBHOOK_HEADERS, "x-360dialog-signature": sig}
    )
    assert r.status_code == 200
