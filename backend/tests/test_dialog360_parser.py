from datetime import UTC, datetime

from app.providers.dialog360 import parser
from tests.helpers import load_fixture

PNID = "109876543210001"
BIZ = "15550001111"


def test_inbound_text_maps_to_canonical_message():
    (change,) = parser.parse(load_fixture("inbound_text"))
    assert change.kind == "messages"
    assert change.phone_number_id == PNID
    assert change.display_phone_number == BIZ
    assert change.waba_id == "102938475610001"
    (msg,) = change.messages
    assert msg.direction == "inbound"
    assert msg.source == "webhook"
    assert msg.contact_wa_id == "919876543210"
    assert msg.contact_name == "Priya Sharma"
    assert msg.business_number == BIZ
    assert msg.type == "text"
    assert msg.text == "Hi, is the 2BHK on MG Road still available?"
    assert msg.sent_at == datetime.fromtimestamp(1759917600, UTC)
    assert msg.status == "received"
    assert msg.media is None


def test_inbound_image_has_media_reference_and_caption():
    (change,) = parser.parse(load_fixture("inbound_image"))
    (msg,) = change.messages
    assert msg.type == "image"
    assert msg.text == "This is the floor plan I got"
    assert msg.media is not None
    assert msg.media.provider_media_id == "1043567891234567"
    assert msg.media.mime_type == "image/jpeg"


def test_mixed_message_types():
    (change,) = parser.parse(load_fixture("inbound_mixed"))
    by_type = {m.type: m for m in change.messages}
    assert by_type["location"].text == "Site office — MG Road, Bengaluru"
    assert by_type["location"].content["latitude"] == 12.9716
    assert by_type["interactive"].text == "Book a site visit"
    assert by_type["button"].text == "Yes, call me"
    assert by_type["button"].context_message_id == "wamid.ECHO.text1"
    assert by_type["contacts"].text == "Rahul Verma"
    assert by_type["reaction"].text == "👍"
    assert by_type["reaction"].content["message_id"] == "wamid.ECHO.text1"
    unsupported = by_type["unsupported"]
    assert unsupported.text is None
    assert unsupported.error_code == "131051"


def test_echo_is_outbound_with_content():
    (change,) = parser.parse(load_fixture("echo_text"))
    assert change.kind == "smb_message_echoes"
    (msg,) = change.messages
    assert msg.direction == "outbound"
    assert msg.source == "echo"
    assert msg.contact_wa_id == "919876543210"
    assert msg.business_number == BIZ
    assert msg.text == "Yes it is! Would you like to visit this weekend?"


def test_statuses_and_errors():
    (change,) = parser.parse(load_fixture("status_failed"))
    assert change.messages == []
    (st,) = change.statuses
    assert st.provider_message_id == "wamid.ECHO.image1"
    assert st.status == "failed"
    assert st.error_code == "131047"
    assert st.error_title == "Re-engagement message"
    assert "24 hours" in (st.error_detail or "")


def test_history_wrapped_format_determines_direction():
    (change,) = parser.parse(load_fixture("history"))
    assert change.kind == "history"
    assert change.phone_number_id == PNID
    msgs = {m.provider_message_id: m for m in change.messages}
    assert msgs["wamid.HIST.1"].direction == "inbound"
    assert msgs["wamid.HIST.1"].status == "received"
    assert msgs["wamid.HIST.2"].direction == "outbound"
    assert msgs["wamid.HIST.2"].status == "read"
    assert msgs["wamid.HIST.2"].contact_wa_id == "918888777766"
    assert msgs["wamid.HIST.3"].media.filename == "requirements.pdf"
    assert all(m.source == "history" for m in change.messages)


def test_state_sync_contacts():
    (change,) = parser.parse(load_fixture("state_sync"))
    (contact,) = change.contacts
    assert contact.wa_id == "919876543210"
    assert contact.saved_name == "Priya S (2BHK lead)"
    assert contact.action == "add"


def test_classify():
    assert parser.classify(load_fixture("inbound_text")) == "messages"
    assert parser.classify(load_fixture("status_read")) == "statuses"
    assert parser.classify(load_fixture("echo_text")) == "smb_message_echoes"
    assert parser.classify(load_fixture("history")) == "history"
    assert parser.classify({"hello": "world"}) is None
    assert parser.classify({"object": "whatsapp_business_account", "entry": "bad"}) is None


def test_unknown_field_is_parsed_without_events():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"field": "account_update", "value": {"event": "X"}}]}],
    }
    (change,) = parser.parse(payload)
    assert change.kind == "account_update"
    assert not change.messages and not change.statuses


def test_malformed_items_are_skipped():
    payload = load_fixture("inbound_text")
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"].append({"type": "text"})  # no id
    value["messages"].append("garbage")
    (change,) = parser.parse(payload)
    assert len(change.messages) == 1
