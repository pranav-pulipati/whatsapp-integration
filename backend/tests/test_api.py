import pytest

from app.db import session_scope
from app.media.storage import InMemoryStorage
from app.models import MessageMedia, User, WebhookEvent
from app.providers.base import FetchedMedia
from app.providers.registry import get_provider
from app.security import hash_password
from app.worker import drain
from tests.conftest import WEBHOOK_HEADERS, make_account
from tests.helpers import fixture_bytes

PASSWORD = "correct horse battery staple"


def make_user(email="admin@example.com", role="admin") -> None:
    with session_scope() as db:
        db.add(User(email=email, password_hash=hash_password(PASSWORD), role=role))


def auth(client, email="admin@example.com", role="admin") -> dict[str, str]:
    make_user(email, role)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def post_webhook(client, account, *fixtures):
    for name in fixtures:
        r = client.post(
            f"/webhooks/360dialog/{account.webhook_token}",
            content=fixture_bytes(name),
            headers=WEBHOOK_HEADERS,
        )
        assert r.status_code == 200
    drain()


# --- auth -----------------------------------------------------------------------


def test_login_and_me(client):
    h = auth(client)
    r = client.get("/api/v1/auth/me", headers=h)
    assert r.json()["email"] == "admin@example.com"
    assert r.json()["role"] == "admin"


def test_login_is_case_insensitive_and_rejects_bad_password(client):
    make_user("Sales@Example.com")
    ok = client.post(
        "/api/v1/auth/login", json={"email": "sales@example.com", "password": PASSWORD}
    )
    assert ok.status_code == 200
    bad = client.post("/api/v1/auth/login", json={"email": "sales@example.com", "password": "nope"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"
    unknown = client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "nope"})
    assert unknown.status_code == 401


def test_login_rate_limited(client):
    make_user()
    for _ in range(10):
        client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "bad"})
    r = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert r.status_code == 429


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/accounts",
        "/api/v1/contacts",
        "/api/v1/conversations",
        "/api/v1/messages",
        "/api/v1/analytics/overview",
        "/api/v1/analytics/timeseries",
        "/api/v1/ops/summary",
    ],
)
def test_endpoints_require_auth(client, path):
    r = client.get(path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert client.get(path, headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_viewer_cannot_use_admin_endpoints(client):
    h = auth(client, "viewer@example.com", "viewer")
    assert client.get("/api/v1/accounts", headers=h).status_code == 200
    body = {"name": "X", "display_phone_number": "+15550003333"}
    assert client.post("/api/v1/accounts", json=body, headers=h).status_code == 403
    assert client.get("/api/v1/ops/summary", headers=h).status_code == 403


# --- accounts -------------------------------------------------------------------


def test_onboard_account_without_code_changes(client):
    h = auth(client)
    body = {
        "name": "Sales — Chennai",
        "display_phone_number": "+91 98765 00006",
        "api_key": "sixth-number-api-key",
        "metadata": {"team": "south"},
    }
    r = client.post("/api/v1/accounts", json=body, headers=h)
    assert r.status_code == 201, r.text
    acc = r.json()
    assert acc["display_phone_number"] == "919876500006"
    assert acc["has_api_key"] is True
    assert acc["status"] == "pending"
    assert acc["health"]["level"] == "no_data"
    assert "api_key" not in acc and "webhook_token" not in str(acc)

    hook = client.get(f"/api/v1/accounts/{acc['id']}/webhook", headers=h).json()
    assert hook["webhook_url"].startswith("http://localhost:8000/webhooks/360dialog/")
    assert hook["secret_header"] == "X-Webhook-Secret"

    dup = client.post("/api/v1/accounts", json=body, headers=h)
    assert dup.status_code == 409


def test_account_validation(client):
    h = auth(client)
    r = client.post("/api/v1/accounts", json={"name": "", "display_phone_number": "12"}, headers=h)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_accounts_list_includes_stats_and_capture_health(client):
    h = auth(client)
    acc = make_account()
    post_webhook(client, acc, "inbound_text", "echo_text", "status_delivered", "status_orphan")
    (row,) = client.get("/api/v1/accounts", headers=h).json()
    assert row["status"] == "active"
    assert row["contacts"] == 1
    assert row["conversations"] == 1
    assert row["messages"] == 2
    assert (row["inbound_messages"], row["outbound_messages"]) == (1, 1)
    health = row["health"]
    assert health["level"] in ("ok", "warning")
    assert health["echoes_7d"] >= 0
    assert health["last_echo_at"] is not None


def test_register_webhook_requires_https_and_key(client, monkeypatch):
    h = auth(client)
    acc = make_account(api_key=None)
    r = client.post(f"/api/v1/accounts/{acc.id}/register-webhook", headers=h)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "missing_api_key"

    acc2 = make_account(display="15550009999", phone_number_id="2")
    r = client.post(f"/api/v1/accounts/{acc2.id}/register-webhook", headers=h)
    assert r.json()["error"]["code"] == "insecure_url"

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_base_url", "https://wa.example.com")
    calls = []
    monkeypatch.setattr(get_provider("360dialog"), "register_webhook", lambda *a: calls.append(a))
    r = client.post(f"/api/v1/accounts/{acc2.id}/register-webhook", headers=h)
    assert r.status_code == 200
    api_key, url, headers = calls[0]
    assert api_key == "test-api-key"
    assert url == f"https://wa.example.com/webhooks/360dialog/{acc2.webhook_token}"
    assert headers == {"X-Webhook-Secret": "test-webhook-shared-secret"}


def test_patch_account_and_rotate_key(client):
    h = auth(client)
    acc = make_account()
    r = client.patch(
        f"/api/v1/accounts/{acc.id}", json={"name": "Renamed", "status": "disabled"}, headers=h
    )
    assert r.json()["name"] == "Renamed" and r.json()["status"] == "disabled"
    r = client.put(f"/api/v1/accounts/{acc.id}/api-key", json={"api_key": "new-key-123"}, headers=h)
    assert r.status_code == 204


# --- end-to-end: webhook → processing → dashboard API ------------------------------


def test_end_to_end_incoming_message_reaches_dashboard(client):
    h = auth(client)
    acc = make_account()
    post_webhook(client, acc, "inbound_text", "echo_text", "status_delivered", "status_read")

    contacts = client.get("/api/v1/contacts", headers=h).json()
    assert contacts["total"] == 1
    c = contacts["items"][0]
    assert c["display_name"] == "Priya Sharma"
    assert c["phone"] == "+919876543210"
    assert c["accounts"][0]["id"] == acc.id
    assert c["conversations"] == 1 and c["messages"] == 2

    convs = client.get("/api/v1/conversations", headers=h).json()
    assert convs["total"] == 1
    conv = convs["items"][0]
    assert conv["account"]["name"] == "Sales — Bengaluru"
    assert conv["contact"]["display_name"] == "Priya Sharma"
    assert conv["last_message"]["direction"] == "outbound"

    timeline = client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=h).json()
    assert [m["direction"] for m in timeline["items"]] == ["inbound", "outbound"]
    out = timeline["items"][1]
    assert out["source"] == "echo"
    assert out["status"] == "read"
    assert [s["status"] for s in out["statuses"]] == ["delivered", "read"]

    ov = client.get(
        "/api/v1/analytics/overview?date_from=2025-10-01T00:00:00Z&date_to=2025-11-01T00:00:00Z",
        headers=h,
    ).json()
    assert ov["accounts"] == 1 and ov["contacts"] == 1 and ov["messages"] == 2
    assert ov["inbound_in_range"] == 1 and ov["outbound_in_range"] == 1
    assert ov["by_account"][0]["inbound"] == 1


def test_conversation_filters_and_search(client):
    h = auth(client)
    a1 = make_account()
    a2 = make_account(
        display="551199990000", phone_number_id="109876543210009", name="Sales — São Paulo"
    )
    post_webhook(client, a1, "inbound_text")
    # brazil fixtures carry a1's metadata; route them to a1 too
    post_webhook(client, a1, "brazil_inbound")

    def total(params):
        return client.get(f"/api/v1/conversations?{params}", headers=h).json()["total"]

    assert total("") == 2
    assert total(f"account_id={a1.id}") == 2
    assert total(f"account_id={a2.id}") == 0
    assert total("q=priya") == 1
    assert total("q=joão") == 1
    assert total("q=98765") == 1
    assert total("q=%25") == 0  # wildcard is escaped
    assert total("status=inactive") == 2  # fixtures are from 2025
    assert total("status=active") == 0
    assert total("date_from=2030-01-01T00:00:00Z") == 0
    assert total("sort=-message_count") == 2
    bad = client.get("/api/v1/conversations?sort=password", headers=h)
    assert bad.status_code == 422


def test_messages_search_and_detail(client):
    h = auth(client)
    acc = make_account()
    post_webhook(client, acc, "inbound_text", "inbound_mixed")
    r = client.get("/api/v1/messages?q=MG%20Road", headers=h).json()
    assert r["total"] == 2  # text + location address
    r = client.get("/api/v1/messages?type=location", headers=h).json()
    (loc,) = r["items"]
    detail = client.get(f"/api/v1/messages/{loc['id']}", headers=h).json()
    assert detail["content"]["latitude"] == 12.9716
    assert client.get("/api/v1/messages/999999", headers=h).status_code == 404


def test_media_download_through_api(client, monkeypatch):
    h = auth(client)
    acc = make_account()
    storage = InMemoryStorage()
    monkeypatch.setattr("app.api.browse.get_storage", lambda: storage)
    monkeypatch.setattr(
        get_provider("360dialog"),
        "fetch_media",
        lambda key, mid: FetchedMedia(content=b"\xff\xd8img", mime_type="image/jpeg"),
    )
    client.post(
        f"/webhooks/360dialog/{acc.webhook_token}",
        content=fixture_bytes("inbound_image"),
        headers=WEBHOOK_HEADERS,
    )
    drain(storage=storage)
    msg = client.get("/api/v1/messages?type=image", headers=h).json()["items"][0]
    assert msg["media"]["available"] is True
    r = client.get(f"/api/v1/messages/{msg['id']}/media", headers=h)
    assert r.status_code == 200
    assert r.content == b"\xff\xd8img"
    assert r.headers["content-type"] == "image/jpeg"
    assert "sandbox" in r.headers["content-security-policy"]
    assert client.get(f"/api/v1/messages/{msg['id']}/media").status_code == 401


def test_media_not_yet_downloaded_is_409(client):
    h = auth(client)
    acc = make_account(api_key=None)
    post_webhook(client, acc, "inbound_image")
    msg = client.get("/api/v1/messages", headers=h).json()["items"][0]
    r = client.get(f"/api/v1/messages/{msg['id']}/media", headers=h)
    assert r.status_code == 409
    with session_scope() as db:
        assert db.query(MessageMedia).one().download_status == "pending"


def test_timeseries_fills_empty_days(client):
    h = auth(client)
    acc = make_account()
    post_webhook(client, acc, "inbound_text", "echo_text")
    r = client.get(
        "/api/v1/analytics/timeseries?date_from=2025-10-07T00:00:00Z&date_to=2025-10-10T00:00:00Z&tz=Asia/Kolkata",
        headers=h,
    )
    assert r.status_code == 200, r.text
    points = r.json()
    assert [p["date"] for p in points] == ["2025-10-07", "2025-10-08", "2025-10-09", "2025-10-10"]
    day = next(p for p in points if p["inbound"])
    assert day["date"] == "2025-10-08"
    assert (day["inbound"], day["outbound"], day["conversations"], day["new_contacts"]) == (
        1,
        1,
        1,
        1,
    )
    assert client.get("/api/v1/analytics/timeseries?tz=Mars/Base", headers=h).status_code == 422
    # legacy alias reported by browsers in India
    assert client.get("/api/v1/analytics/timeseries?tz=Asia/Calcutta", headers=h).status_code == 200


def test_ops_retry_dead_event(client):
    h = auth(client)
    acc = make_account()
    payload = fixture_bytes("inbound_text").replace(b"109876543210001", b"999")
    client.post(
        f"/webhooks/360dialog/{acc.webhook_token}", content=payload, headers=WEBHOOK_HEADERS
    )
    drain()
    dead = client.get("/api/v1/ops/webhook-events?status=dead", headers=h).json()
    assert dead["total"] == 1
    assert "mismatch" in dead["items"][0]["last_error"]
    r = client.post(f"/api/v1/ops/webhook-events/{dead['items'][0]['id']}/retry", headers=h)
    assert r.json()["status"] == "pending"
    summary = client.get("/api/v1/ops/summary", headers=h).json()
    assert summary["events"] == {"pending": 1}
    with session_scope() as db:
        assert db.query(WebhookEvent).one().attempts == 0


def test_openapi_document_is_generated(client):
    spec = client.get("/api/openapi.json").json()
    paths = spec["paths"]
    for p in (
        "/api/v1/accounts",
        "/api/v1/contacts",
        "/api/v1/conversations",
        "/api/v1/messages",
        "/api/v1/analytics/overview",
        "/webhooks/{provider_name}/{webhook_token}",
    ):
        assert p in paths


def test_health(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok"}
