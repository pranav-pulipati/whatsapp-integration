"""Provider-neutral event model and provider interface.

Providers translate their webhook payloads into these canonical events; the rest
of the application (processor, API, dashboard) never sees provider payloads.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

Direction = Literal["inbound", "outbound"]
MessageSource = Literal["webhook", "echo", "history"]


class WebhookAuthError(Exception):
    """The request could not be authenticated."""


class ProviderError(Exception):
    """A call to the provider API failed."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class MediaRef:
    provider_media_id: str | None
    mime_type: str | None = None
    sha256: str | None = None
    filename: str | None = None
    caption: str | None = None


@dataclass(frozen=True)
class MessageEvent:
    provider_message_id: str
    direction: Direction
    source: MessageSource
    contact_wa_id: str
    business_number: str
    sent_at: datetime
    type: str
    text: str | None = None
    content: dict[str, Any] = field(default_factory=dict)
    media: MediaRef | None = None
    context_message_id: str | None = None
    contact_name: str | None = None
    status: str | None = None  # initial status, e.g. 'received' or history state
    error_code: str | None = None
    error_title: str | None = None


@dataclass(frozen=True)
class StatusEvent:
    provider_message_id: str
    status: str
    occurred_at: datetime
    recipient_wa_id: str | None = None
    error_code: str | None = None
    error_title: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class ContactEvent:
    """Address-book sync from the WhatsApp Business App."""

    wa_id: str
    saved_name: str | None
    action: str
    occurred_at: datetime | None


@dataclass
class ParsedChange:
    """Everything one payload says about one business phone number."""

    kind: str
    phone_number_id: str | None = None
    display_phone_number: str | None = None
    waba_id: str | None = None
    messages: list[MessageEvent] = field(default_factory=list)
    statuses: list[StatusEvent] = field(default_factory=list)
    contacts: list[ContactEvent] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FetchedMedia:
    content: bytes
    mime_type: str | None


class Provider(Protocol):
    name: str

    def authenticate(self, headers: Mapping[str, str], body: bytes) -> None:
        """Provider-specific authenticity check (e.g. HMAC). Raises WebhookAuthError."""

    def classify(self, payload: dict[str, Any]) -> str | None:
        """Cheap shape check used inside the webhook request.
        Returns an event kind, or None if the payload shape is not recognised."""

    def parse(self, payload: dict[str, Any]) -> list[ParsedChange]:
        """Full translation into canonical events (runs in the worker)."""

    def fetch_media(self, api_key: str, provider_media_id: str) -> FetchedMedia: ...

    def register_webhook(self, api_key: str, url: str, headers: dict[str, str]) -> None: ...
