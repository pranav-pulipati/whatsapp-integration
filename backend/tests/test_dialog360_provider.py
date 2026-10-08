import hashlib
import hmac
import json

import httpx
import pytest

from app.config import Settings
from app.phone import equivalent_ids
from app.providers.base import ProviderError, WebhookAuthError
from app.providers.dialog360.provider import Dialog360Provider

BASE = "https://waba-v2.360dialog.io"


def _provider(handler=None, **overrides) -> Dialog360Provider:
    settings = Settings(app_env="test", dialog360_api_base_url=BASE, **overrides)
    transport = httpx.MockTransport(handler) if handler else None
    return Dialog360Provider(settings, transport=transport)


def test_signature_valid_and_invalid():
    p = _provider(dialog360_platform_secret="platform-secret")
    body = b'{"a":1}'
    sig = hmac.new(b"platform-secret", body, hashlib.sha256).hexdigest()
    p.authenticate({"x-360dialog-signature": sig}, body)
    p.authenticate({"x-360dialog-signature": f"sha256={sig}"}, body)
    with pytest.raises(WebhookAuthError):
        p.authenticate({"x-360dialog-signature": "deadbeef"}, body)


def test_signature_optional_unless_required():
    _provider(dialog360_platform_secret="s").authenticate({}, b"{}")
    with pytest.raises(WebhookAuthError):
        _provider(dialog360_platform_secret="s", dialog360_require_signature=True).authenticate(
            {}, b"{}"
        )


def test_fetch_media_rewrites_lookaside_host_and_sends_key():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.url.path, request.headers.get("D360-API-KEY")))
        if request.url.path == "/1043567891234567":
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1&ext=2&hash=3",
                    "mime_type": "image/jpeg",
                },
            )
        return httpx.Response(200, content=b"\xff\xd8jpeg-bytes", headers={"content-type": "image/jpeg"})

    media = _provider(handler).fetch_media("key-123", "1043567891234567")
    assert media.content == b"\xff\xd8jpeg-bytes"
    assert media.mime_type == "image/jpeg"
    assert seen[1][0] == "waba-v2.360dialog.io"
    assert seen[1][1] == "/whatsapp_business/attachments/"
    assert all(s[2] == "key-123" for s in seen)


def test_fetch_media_refuses_foreign_hosts():
    def handler(request):
        return httpx.Response(200, json={"url": "https://evil.example.com/steal"})

    with pytest.raises(ProviderError) as exc:
        _provider(handler).fetch_media("k", "1")
    assert not exc.value.retryable


def test_fetch_media_size_limit():
    def handler(request):
        if request.url.path == "/1":
            return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/x"})
        return httpx.Response(200, content=b"x" * 100)

    with pytest.raises(ProviderError):
        _provider(handler, media_max_bytes=10).fetch_media("k", "1")


def test_http_errors_classified_as_retryable_or_not():
    def handler_500(request):
        return httpx.Response(503)

    def handler_401(request):
        return httpx.Response(401)

    with pytest.raises(ProviderError) as e1:
        _provider(handler_500).fetch_media("k", "1")
    assert e1.value.retryable
    with pytest.raises(ProviderError) as e2:
        _provider(handler_401).fetch_media("k", "1")
    assert not e2.value.retryable


def test_register_webhook_payload():
    captured = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"url": "ok"})

    _provider(handler).register_webhook("k", "https://x.example.com/hook", {"X-Webhook-Secret": "s"})
    assert captured["path"] == "/v1/configs/webhook"
    assert captured["body"] == {
        "url": "https://x.example.com/hook",
        "headers": {"X-Webhook-Secret": "s"},
    }


@pytest.mark.parametrize(
    ("wa_id", "variant"),
    [
        ("551199998888", "5511999998888"),
        ("5511999998888", "551199998888"),
        ("5215512345678", "525512345678"),
        ("525512345678", "5215512345678"),
    ],
)
def test_equivalent_ids(wa_id, variant):
    assert variant in equivalent_ids(wa_id)


def test_equivalent_ids_plain_number():
    assert equivalent_ids("+91 98765 43210") == ["919876543210"]
