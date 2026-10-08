from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.phone import digits


class Paginated[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


# --- auth -----------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_at: datetime
    user: UserOut


# --- accounts -------------------------------------------------------------------


class AccountRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    display_phone_number: str


class CaptureHealth(BaseModel):
    """Pilot signal: are inbound messages AND app-sent replies (echoes) arriving?"""

    level: Literal["ok", "warning", "no_data"]
    reasons: list[str]
    last_event_at: datetime | None
    last_inbound_at: datetime | None
    last_echo_at: datetime | None
    inbound_7d: int
    echoes_7d: int
    orphan_statuses_7d: int
    failed_events: int


class AccountOut(BaseModel):
    id: int
    provider: str
    provider_account_id: str | None
    waba_id: str | None
    phone_number_id: str | None
    display_phone_number: str
    name: str
    status: str
    has_api_key: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    contacts: int = 0
    conversations: int = 0
    active_conversations: int = 0
    messages: int = 0
    inbound_messages: int = 0
    outbound_messages: int = 0
    messages_7d: int = 0
    health: CaptureHealth | None = None


def _phone(v: str) -> str:
    d = digits(v)
    if not 7 <= len(d) <= 15:
        raise ValueError("must be an international phone number (7–15 digits)")
    return d


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    display_phone_number: str = Field(description="International format, e.g. +91 98765 43210")
    provider: Literal["360dialog"] = "360dialog"
    provider_account_id: str | None = Field(
        None, max_length=128, description="360dialog channel id"
    )
    waba_id: str | None = Field(None, max_length=64)
    phone_number_id: str | None = Field(None, max_length=64)
    api_key: str | None = Field(None, min_length=8, max_length=512, description="Stored encrypted")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("display_phone_number")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return _phone(v)


class AccountUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    status: Literal["pending", "active", "disabled"] | None = None
    provider_account_id: str | None = Field(None, max_length=128)
    waba_id: str | None = Field(None, max_length=64)
    phone_number_id: str | None = Field(None, max_length=64)
    metadata: dict[str, Any] | None = None


class ApiKeyUpdate(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)


class WebhookInfo(BaseModel):
    webhook_url: str
    secret_header: str
    registered: bool | None = None


# --- contacts / conversations / messages -----------------------------------------


class ContactRef(BaseModel):
    id: int
    wa_id: str
    phone: str | None
    display_name: str


class ContactOut(ContactRef):
    name: str | None
    saved_name: str | None
    first_seen_at: datetime
    last_activity_at: datetime
    conversations: int
    messages: int
    accounts: list[AccountRef]


class MessagePreview(BaseModel):
    type: str
    text: str | None
    direction: str
    sent_at: datetime


class ConversationOut(BaseModel):
    id: int
    account: AccountRef
    contact: ContactRef
    status: Literal["active", "inactive"]
    started_at: datetime
    last_message_at: datetime
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    message_count: int
    inbound_count: int
    outbound_count: int
    assigned_agent: str | None
    last_message: MessagePreview | None = None


class MediaOut(BaseModel):
    id: int
    mime_type: str | None
    filename: str | None
    size_bytes: int | None
    download_status: str
    available: bool


class StatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str
    occurred_at: datetime
    error_code: str | None
    error_title: str | None
    error_detail: str | None


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    account_id: int
    contact_id: int
    provider_message_id: str
    direction: str
    source: str
    sender: str
    recipient: str
    type: str
    text: str | None
    content: dict[str, Any]
    context_message_id: str | None
    sent_at: datetime
    status: str | None
    status_at: datetime | None
    error_code: str | None
    error_title: str | None
    media: MediaOut | None
    statuses: list[StatusOut] | None = None


# --- analytics ------------------------------------------------------------------


class AccountActivity(BaseModel):
    account: AccountRef
    inbound: int
    outbound: int
    conversations: int


class Overview(BaseModel):
    range_from: datetime
    range_to: datetime
    accounts: int
    contacts: int
    conversations: int
    messages: int
    active_conversations: int
    inbound_in_range: int
    outbound_in_range: int
    new_contacts_in_range: int
    conversations_in_range: int
    by_account: list[AccountActivity]


class TimeseriesPoint(BaseModel):
    date: str
    inbound: int
    outbound: int
    conversations: int
    new_contacts: int


# --- ops ------------------------------------------------------------------------


class WebhookEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    account_id: int | None
    source: str
    event_kind: str | None
    status: str
    attempts: int
    last_error: str | None
    received_at: datetime
    processed_at: datetime | None
    next_attempt_at: datetime
