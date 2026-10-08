"""Canonical data model.

This schema is ours, not 360dialog's: providers are mapped into it by
`app.providers.*`. Key idempotency guarantees live here as unique constraints:

- messages:          (account_id, provider_message_id)
- message_statuses:  (account_id, provider_message_id, status)
- contacts:          wa_id
- conversations:     (account_id, contact_id)
- webhook_events:    (provider, payload_sha256)
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, datetime: DateTime(timezone=True)}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class User(TimestampMixin, Base):
    """Dashboard users (internal staff)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'viewer')", name="ck_users_role"),
        Index("uq_users_email_lower", func.lower(sql_text("email")), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None]


class WhatsAppAccount(TimestampMixin, Base):
    """One connected WhatsApp Business phone number. Adding a number = adding a row."""

    __tablename__ = "whatsapp_accounts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'disabled', 'error')", name="ck_accounts_status"
        ),
        Index(
            "uq_accounts_provider_phone_number_id",
            "provider",
            "phone_number_id",
            unique=True,
            postgresql_where=sql_text("phone_number_id IS NOT NULL"),
        ),
        UniqueConstraint("display_phone_number", name="uq_accounts_display_phone_number"),
        UniqueConstraint("webhook_token", name="uq_accounts_webhook_token"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_account_id: Mapped[str | None] = mapped_column(String(128))
    waba_id: Mapped[str | None] = mapped_column(String(64))
    phone_number_id: Mapped[str | None] = mapped_column(String(64))
    display_phone_number: Mapped[str] = mapped_column(String(32))  # digits only, E.164 sans '+'
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    webhook_token: Mapped[str] = mapped_column(String(64))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    # Capture-health signals (updated by the processor).
    last_event_at: Mapped[datetime | None]
    last_inbound_at: Mapped[datetime | None]
    last_echo_at: Mapped[datetime | None]


class Contact(TimestampMixin, Base):
    """A WhatsApp user. Shared across numbers so one customer appears once."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("wa_id", name="uq_contacts_wa_id"),
        Index("ix_contacts_last_activity_at", "last_activity_at"),
        # Trigram search index (ix_contacts_search_trgm) is created in the migration.
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(32))
    phone: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(256))  # WhatsApp profile name
    saved_name: Mapped[str | None] = mapped_column(String(256))  # Business App address book
    name_observed_at: Mapped[datetime | None]
    first_seen_at: Mapped[datetime]
    last_activity_at: Mapped[datetime]


class Conversation(TimestampMixin, Base):
    """The chat thread between one WhatsApp number and one contact."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("account_id", "contact_id", name="uq_conversations_account_contact"),
        Index("ix_conversations_last_message_at", "last_message_at"),
        Index("ix_conversations_account_last_message", "account_id", "last_message_at"),
        Index("ix_conversations_contact_id", "contact_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_accounts.id", ondelete="CASCADE"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    started_at: Mapped[datetime]
    last_message_at: Mapped[datetime]
    last_inbound_at: Mapped[datetime | None]
    last_outbound_at: Mapped[datetime | None]
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    inbound_count: Mapped[int] = mapped_column(Integer, default=0)
    outbound_count: Mapped[int] = mapped_column(Integer, default=0)
    # Not provided by WhatsApp/360dialog webhooks; reserved for a future source.
    assigned_agent: Mapped[str | None] = mapped_column(String(200))

    account: Mapped[WhatsAppAccount] = relationship(lazy="joined")
    contact: Mapped[Contact] = relationship(lazy="joined")


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "provider_message_id", name="uq_messages_account_provider_id"
        ),
        CheckConstraint("direction IN ('inbound', 'outbound')", name="ck_messages_direction"),
        CheckConstraint("source IN ('webhook', 'echo', 'history')", name="ck_messages_source"),
        Index("ix_messages_conversation_sent_at", "conversation_id", "sent_at"),
        Index("ix_messages_account_sent_at", "account_id", "sent_at"),
        Index("ix_messages_sent_at", "sent_at"),
        # Trigram search index (ix_messages_text_trgm) is created in the migration.
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_accounts.id", ondelete="CASCADE"))
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    provider_message_id: Mapped[str] = mapped_column(String(256))
    direction: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(16))
    sender: Mapped[str] = mapped_column(String(32))
    recipient: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(32))
    text: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    context_message_id: Mapped[str | None] = mapped_column(String(256))
    sent_at: Mapped[datetime]
    # Latest delivery state for outbound; 'received' for inbound.
    status: Mapped[str | None] = mapped_column(String(16))
    status_at: Mapped[datetime | None]
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_title: Mapped[str | None] = mapped_column(Text)

    media: Mapped["MessageMedia | None"] = relationship(back_populates="message", lazy="selectin")


class MessageStatus(Base):
    """Append-only delivery status history. message_id is NULL until the message is
    known (statuses can arrive before the message itself); such rows are 'orphans'."""

    __tablename__ = "message_statuses"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "provider_message_id",
            "status",
            name="uq_message_statuses_account_msg_status",
        ),
        Index("ix_message_statuses_message_id", "message_id"),
        Index(
            "ix_message_statuses_orphans",
            "account_id",
            "provider_message_id",
            postgresql_where=sql_text("message_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_accounts.id", ondelete="CASCADE"))
    provider_message_id: Mapped[str] = mapped_column(String(256))
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16))
    occurred_at: Mapped[datetime]
    recipient: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_title: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class MessageMedia(TimestampMixin, Base):
    """Media metadata. Bytes live in object storage under `storage_key`."""

    __tablename__ = "message_media"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_message_media_message_id"),
        CheckConstraint(
            "download_status IN ('pending', 'downloaded', 'failed', 'skipped')",
            name="ck_message_media_download_status",
        ),
        Index(
            "ix_message_media_pending",
            "next_attempt_at",
            postgresql_where=sql_text("download_status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_accounts.id", ondelete="CASCADE"))
    provider_media_id: Mapped[str | None] = mapped_column(String(256))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    sha256: Mapped[str | None] = mapped_column(String(128))
    filename: Mapped[str | None] = mapped_column(String(512))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    download_status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    downloaded_at: Mapped[datetime | None]

    message: Mapped[Message] = relationship(back_populates="media")


class WebhookEvent(Base):
    """Raw inbound provider event + durable processing queue.

    Webhook requests only insert here; the worker claims rows with
    SELECT ... FOR UPDATE SKIP LOCKED and processes them asynchronously.
    """

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "payload_sha256", name="uq_webhook_events_provider_sha"),
        CheckConstraint(
            "status IN ('pending', 'retry', 'processed', 'ignored', 'dead')",
            name="ck_webhook_events_status",
        ),
        CheckConstraint("source IN ('webhook', 'history_import')", name="ck_webhook_events_source"),
        Index(
            "ix_webhook_events_due",
            "next_attempt_at",
            postgresql_where=sql_text("status IN ('pending', 'retry')"),
        ),
        Index("ix_webhook_events_status_received", "status", "received_at"),
        Index("ix_webhook_events_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("whatsapp_accounts.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(16), default="webhook")
    event_kind: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None]
