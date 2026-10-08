"""360dialog provider: webhook authenticity, parsing, media download, webhook setup.

API facts used here (see docs/360dialog.md):
- Base URL https://waba-v2.360dialog.io, header `D360-API-KEY` (one key per number).
- GET /{media-id} returns a lookaside.fbsbx.com URL; download it by swapping the
  host for the 360dialog base URL and sending the same API key.
- POST /v1/configs/webhook {"url": ..., "headers": {...}} sets a number's webhook.
- Optional HMAC-SHA256 of the body in `x-360dialog-signature` (platform secret).
"""

import hashlib
import hmac
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import Settings, get_settings
from app.providers.base import (
    FetchedMedia,
    ParsedChange,
    ProviderError,
    WebhookAuthError,
)
from app.providers.dialog360 import parser

SIGNATURE_HEADER = "x-360dialog-signature"
META_MEDIA_HOST = "lookaside.fbsbx.com"


class Dialog360Provider:
    name = "360dialog"

    def __init__(
        self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None
    ):
        self.settings = settings or get_settings()
        self._transport = transport

    # --- webhooks -----------------------------------------------------------

    def authenticate(self, headers: Mapping[str, str], body: bytes) -> None:
        secret = self.settings.dialog360_platform_secret
        signature = headers.get(SIGNATURE_HEADER)
        if not secret:
            return
        if not signature:
            if self.settings.dialog360_require_signature:
                raise WebhookAuthError("missing signature")
            return
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        provided = signature.removeprefix("sha256=").strip().lower()
        if not hmac.compare_digest(expected, provided):
            raise WebhookAuthError("invalid signature")

    def classify(self, payload: dict[str, Any]) -> str | None:
        return parser.classify(payload)

    def parse(self, payload: dict[str, Any]) -> list[ParsedChange]:
        return parser.parse(payload)

    # --- API calls ----------------------------------------------------------

    def _client(self, api_key: str) -> httpx.Client:
        return httpx.Client(
            base_url=self.settings.dialog360_api_base_url,
            headers={"D360-API-KEY": api_key},
            timeout=self.settings.dialog360_timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
        )

    def fetch_media(self, api_key: str, provider_media_id: str) -> FetchedMedia:
        with self._client(api_key) as client:
            meta = self._request(client, "GET", f"/{provider_media_id}")
            info = meta.json()
            url = info.get("url")
            if not isinstance(url, str):
                raise ProviderError("media metadata has no url", retryable=False)
            download_url = self._rewrite_media_url(url)
            limit = self.settings.media_max_bytes
            with client.stream("GET", download_url) as resp:
                self._raise_for_status(resp)
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ProviderError(f"media exceeds {limit} bytes", retryable=False)
                    chunks.append(chunk)
            return FetchedMedia(
                content=b"".join(chunks),
                mime_type=info.get("mime_type") or resp.headers.get("content-type"),
            )

    def register_webhook(self, api_key: str, url: str, headers: dict[str, str]) -> None:
        with self._client(api_key) as client:
            self._request(
                client, "POST", "/v1/configs/webhook", json={"url": url, "headers": headers}
            )

    def _rewrite_media_url(self, url: str) -> str:
        """Only ever send the API key to the 360dialog host (prevents SSRF/key leaks)."""
        parts = urlsplit(url)
        base = urlsplit(self.settings.dialog360_api_base_url)
        if parts.scheme != "https" or parts.hostname not in (META_MEDIA_HOST, base.hostname):
            raise ProviderError("unexpected media URL host", retryable=False)
        return urlunsplit((base.scheme, base.netloc, parts.path, parts.query, ""))

    def _request(
        self, client: httpx.Client, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        try:
            resp = client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"360dialog request failed: {type(exc).__name__}") from exc
        self._raise_for_status(resp)
        return resp

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        retryable = resp.status_code == 429 or resp.status_code >= 500
        raise ProviderError(f"360dialog returned HTTP {resp.status_code}", retryable=retryable)
