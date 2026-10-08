import copy
import json

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.ingestion.webhook import store_event
from app.media.storage import InMemoryStorage
from app.models import (
    Contact,
    Conversation,
    Message,
    MessageMedia,
    MessageStatus,
    WebhookEvent,
    WhatsAppAccount,
)
from app.providers.base import FetchedMedia, ProviderError
from app.providers.registry import get_provider
from app.worker import drain
from tests.conftest import make_account
from tests.helpers import load_fixture


def deliver(account, payload: dict, source: str = "webhook") -> None:
    raw = json.dumps(payload, sort_keys=True).encode()
    kind = get_provider("360dialog").classify(payload)
    with session_scope() as db:
        store_event(
            db,
            provider="360dialog",
            account_id=account.id,
            payload=payload,
            raw=raw,
            kind=kind,
            source=source,
        )


def deliver_fixture(account, *names: str) -> None:
    for name in names:
        deliver(account, load_fixture(name))
    drain()


def count(model) -> int:
    with session_scope() as db:
        return db.scalar(select(func.count()).select_from(model))


def one(model, *where):
    with session_scope() as db:
        return db.execute(select(model).where(*where)).scalars().one()


def test_inbound_message_creates_contact_conversation_message(account):
    deliver_fixture(account, "inbound_text")
    contact = one(Contact)
    assert contact.wa_id == "919876543210"
    assert contact.name == "Priya Sharma"
    conv = one(Conversation)
    assert (conv.account_id, conv.contact_id) == (account.id, contact.id)
    assert (conv.message_count, conv.inbound_count, conv.outbound_count) == (1, 1, 0)
    msg = one(Message)
    assert msg.direction == "inbound"
    assert msg.sender == "919876543210" and msg.recipient == "15550001111"
    assert msg.status == "received"
    acc = one(WhatsAppAccount)
    assert acc.status == "active"
    assert acc.last_inbound_at == msg.sent_at
    assert one(WebhookEvent).status == "processed"


def test_redelivered_message_with_different_bytes_is_not_duplicated(account):
    payload = load_fixture("inbound_text")
    deliver(account, payload)
    reformatted = copy.deepcopy(payload)
    reformatted["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"] = "Priya"
    deliver(account, reformatted)
    drain()
    assert count(WebhookEvent) == 2
    assert count(Message) == 1
    assert one(Conversation).message_count == 1


def test_app_sent_echo_lands_in_same_conversation(account):
    deliver_fixture(account, "inbound_text", "echo_text")
    assert count(Conversation) == 1
    out = one(Message, Message.direction == "outbound")
    assert out.source == "echo"
    assert out.text == "Yes it is! Would you like to visit this weekend?"
    assert out.sender == "15550001111" and out.recipient == "919876543210"
    conv = one(Conversation)
    assert (conv.inbound_count, conv.outbound_count) == (1, 1)
    assert conv.last_outbound_at == out.sent_at
    assert one(WhatsAppAccount).last_echo_at == out.sent_at


def test_statuses_out_of_order_never_regress(account):
    deliver_fixture(account, "echo_text", "status_read", "status_delivered")
    msg = one(Message)
    assert msg.status == "read"
    assert count(MessageStatus) == 2


def test_status_before_echo_is_attached_later(account):
    deliver_fixture(account, "status_delivered")
    orphan = one(MessageStatus)
    assert orphan.message_id is None
    deliver_fixture(account, "echo_text")
    msg = one(Message)
    assert msg.status == "delivered"
    assert one(MessageStatus).message_id == msg.id


def test_duplicate_status_is_ignored(account):
    deliver_fixture(account, "echo_text", "status_delivered")
    payload = load_fixture("status_delivered")
    payload["entry"][0]["changes"][0]["value"]["statuses"][0]["conversation"] = {"id": "x"}
    deliver(account, payload)
    drain()
    assert count(MessageStatus) == 1


def test_failed_status_records_error(account):
    deliver_fixture(account, "echo_image", "status_failed")
    msg = one(Message)
    assert msg.status == "failed"
    assert msg.error_code == "131047"


def test_older_message_does_not_rewind_activity(account):
    deliver_fixture(account, "inbound_image")  # later timestamp
    deliver_fixture(account, "inbound_text")  # earlier timestamp, arrives late
    conv = one(Conversation)
    first, last = sorted(m.sent_at for m in _all(Message))
    assert conv.started_at == first
    assert conv.last_message_at == last
    contact = one(Contact)
    assert contact.first_seen_at == first and contact.last_activity_at == last


def _all(model):
    with session_scope() as db:
        return db.execute(select(model)).scalars().all()


def test_brazil_number_variants_correlate_to_one_contact(account):
    deliver_fixture(account, "brazil_inbound", "brazil_echo")
    assert count(Contact) == 1
    assert count(Conversation) == 1
    assert one(Contact).wa_id == "551199998888"


def test_echo_first_then_inbound_adopts_authoritative_wa_id(account):
    deliver_fixture(account, "brazil_echo")
    assert one(Contact).wa_id == "5511999998888"
    deliver_fixture(account, "brazil_inbound")
    assert count(Contact) == 1
    assert one(Contact).wa_id == "551199998888"
    assert one(Contact).name == "João Silva"


def test_same_customer_on_two_numbers_shares_contact(account):
    other = make_account(
        display="15550002222", phone_number_id="109876543210002", name="Sales — Pune"
    )
    deliver_fixture(account, "inbound_text")
    payload = load_fixture("inbound_text")
    meta = payload["entry"][0]["changes"][0]["value"]["metadata"]
    meta["display_phone_number"], meta["phone_number_id"] = "15550002222", "109876543210002"
    deliver(other, payload)
    drain()
    assert count(Contact) == 1
    assert count(Conversation) == 2
    assert count(Message) == 2  # same wamid on different numbers is a different message


def test_event_for_wrong_number_is_rejected_not_misfiled(account):
    payload = load_fixture("inbound_text")
    payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "999"
    deliver(account, payload)
    drain()
    ev = one(WebhookEvent)
    assert ev.status == "dead"
    assert "phone_number_id mismatch" in ev.last_error
    assert count(Message) == 0


def test_unknown_phone_number_id_is_learned_from_first_event():
    acc = make_account(phone_number_id=None)
    deliver_fixture(acc, "inbound_text")
    assert one(WhatsAppAccount).phone_number_id == "109876543210001"


def test_history_import_is_idempotent(account):
    deliver(account, load_fixture("history"), source="history_import")
    drain()
    msgs = {m.provider_message_id: m for m in _all(Message)}
    assert len(msgs) == 3
    assert msgs["wamid.HIST.2"].direction == "outbound"
    assert msgs["wamid.HIST.2"].status == "read"
    assert all(m.source == "history" for m in msgs.values())
    payload = load_fixture("history")
    payload["id"] = "EVT-HISTORY-REPLAY"
    deliver(account, payload, source="history_import")
    drain()
    assert count(Message) == 3
    assert one(Conversation).message_count == 3


def test_address_book_sync_sets_saved_name(account):
    deliver_fixture(account, "inbound_text", "state_sync")
    c = one(Contact)
    assert c.saved_name == "Priya S (2BHK lead)"
    assert c.name == "Priya Sharma"


def test_mixed_types_are_all_stored(account):
    deliver_fixture(account, "inbound_mixed")
    types = sorted(m.type for m in _all(Message))
    assert types == ["button", "contacts", "interactive", "location", "reaction", "unsupported"]


def test_media_is_downloaded_to_object_storage(account, monkeypatch):
    provider = get_provider("360dialog")
    calls = []

    def fake_fetch(api_key, media_id):
        calls.append((api_key, media_id))
        return FetchedMedia(content=b"jpeg-bytes", mime_type="image/jpeg")

    monkeypatch.setattr(provider, "fetch_media", fake_fetch)
    storage = InMemoryStorage()
    deliver(account, load_fixture("inbound_image"))
    drain(storage=storage)
    media = one(MessageMedia)
    assert media.download_status == "downloaded"
    assert media.size_bytes == len(b"jpeg-bytes")
    assert storage.objects[media.storage_key][0] == b"jpeg-bytes"
    assert calls == [("test-api-key", "1043567891234567")]


def test_media_without_api_key_retries_then_fails(monkeypatch):
    acc = make_account(api_key=None)
    deliver_fixture(acc, "inbound_image")
    media = one(MessageMedia)
    assert media.download_status == "pending"
    assert media.attempts == 1
    assert "no API key" in media.last_error


def test_non_retryable_media_error_fails_immediately(account, monkeypatch):
    def fake_fetch(api_key, media_id):
        raise ProviderError("360dialog returned HTTP 404", retryable=False)

    monkeypatch.setattr(get_provider("360dialog"), "fetch_media", fake_fetch)
    deliver_fixture(account, "inbound_image")
    assert one(MessageMedia).download_status == "failed"
    assert count(Message) == 1  # the message itself is safe


def test_processing_errors_are_retried_with_backoff_then_dead(account, monkeypatch):
    from app import config
    from app.ingestion import processor

    def boom(*a, **k):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(processor, "upsert_message", boom)
    deliver_fixture(account, "inbound_text")
    ev = one(WebhookEvent)
    assert ev.status == "retry"
    assert ev.attempts == 1
    assert ev.next_attempt_at > ev.received_at

    monkeypatch.setattr(config.get_settings(), "event_max_attempts", 2)
    with session_scope() as db:
        db.get(WebhookEvent, ev.id).next_attempt_at = ev.received_at
    drain()
    ev = one(WebhookEvent)
    assert ev.status == "dead"
    assert "database hiccup" in ev.last_error
    assert count(Message) == 0


@pytest.mark.parametrize("fixture", ["status_orphan"])
def test_orphan_status_stays_visible(account, fixture):
    deliver_fixture(account, fixture)
    st = one(MessageStatus)
    assert st.message_id is None
