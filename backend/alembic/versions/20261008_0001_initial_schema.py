"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-08 15:46:38.297690
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Trigram indexes power ILIKE search on contact names/numbers and message text.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "contacts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("wa_id", sa.String(length=32), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=True),
        sa.Column("saved_name", sa.String(length=256), nullable=True),
        sa.Column("name_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wa_id", name="uq_contacts_wa_id"),
    )
    op.create_index("ix_contacts_last_activity_at", "contacts", ["last_activity_at"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('admin', 'viewer')", name="ck_users_role"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "whatsapp_accounts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_account_id", sa.String(length=128), nullable=True),
        sa.Column("waba_id", sa.String(length=64), nullable=True),
        sa.Column("phone_number_id", sa.String(length=64), nullable=True),
        sa.Column("display_phone_number", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("webhook_token", sa.String(length=64), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_echo_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'disabled', 'error')", name="ck_accounts_status"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("display_phone_number", name="uq_accounts_display_phone_number"),
        sa.UniqueConstraint("webhook_token", name="uq_accounts_webhook_token"),
    )
    op.create_index(
        "uq_accounts_provider_phone_number_id",
        "whatsapp_accounts",
        ["provider", "phone_number_id"],
        unique=True,
        postgresql_where=sa.text("phone_number_id IS NOT NULL"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("inbound_count", sa.Integer(), nullable=False),
        sa.Column("outbound_count", sa.Integer(), nullable=False),
        sa.Column("assigned_agent", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["whatsapp_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "contact_id", name="uq_conversations_account_contact"),
    )
    op.create_index(
        "ix_conversations_account_last_message",
        "conversations",
        ["account_id", "last_message_at"],
        unique=False,
    )
    op.create_index("ix_conversations_contact_id", "conversations", ["contact_id"], unique=False)
    op.create_index(
        "ix_conversations_last_message_at", "conversations", ["last_message_at"], unique=False
    )
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("event_kind", sa.String(length=64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source IN ('webhook', 'history_import')", name="ck_webhook_events_source"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'retry', 'processed', 'ignored', 'dead')",
            name="ck_webhook_events_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["whatsapp_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "payload_sha256", name="uq_webhook_events_provider_sha"),
    )
    op.create_index("ix_webhook_events_account_id", "webhook_events", ["account_id"], unique=False)
    op.create_index(
        "ix_webhook_events_due",
        "webhook_events",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'retry')"),
    )
    op.create_index(
        "ix_webhook_events_status_received",
        "webhook_events",
        ["status", "received_at"],
        unique=False,
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=256), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("sender", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("context_message_id", sa.String(length=256), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("error_title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("direction IN ('inbound', 'outbound')", name="ck_messages_direction"),
        sa.CheckConstraint("source IN ('webhook', 'echo', 'history')", name="ck_messages_source"),
        sa.ForeignKeyConstraint(["account_id"], ["whatsapp_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "provider_message_id", name="uq_messages_account_provider_id"
        ),
    )
    op.create_index(
        "ix_messages_account_sent_at", "messages", ["account_id", "sent_at"], unique=False
    )
    op.create_index(
        "ix_messages_conversation_sent_at", "messages", ["conversation_id", "sent_at"], unique=False
    )
    op.create_index("ix_messages_sent_at", "messages", ["sent_at"], unique=False)
    op.create_table(
        "message_media",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_media_id", sa.String(length=256), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("sha256", sa.String(length=128), nullable=True),
        sa.Column("filename", sa.String(length=512), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("download_status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "download_status IN ('pending', 'downloaded', 'failed', 'skipped')",
            name="ck_message_media_download_status",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["whatsapp_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_message_media_message_id"),
    )
    op.create_index(
        "ix_message_media_pending",
        "message_media",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("download_status = 'pending'"),
    )
    op.create_table(
        "message_statuses",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=256), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipient", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("error_title", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["whatsapp_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "provider_message_id",
            "status",
            name="uq_message_statuses_account_msg_status",
        ),
    )
    op.create_index(
        "ix_message_statuses_message_id", "message_statuses", ["message_id"], unique=False
    )
    op.create_index(
        "ix_message_statuses_orphans",
        "message_statuses",
        ["account_id", "provider_message_id"],
        unique=False,
        postgresql_where=sa.text("message_id IS NULL"),
    )
    op.execute(
        "CREATE INDEX ix_contacts_search_trgm ON contacts USING gin "
        "((coalesce(name, '') || ' ' || coalesce(saved_name, '') || ' ' || wa_id) gin_trgm_ops)"
    )
    op.execute("CREATE INDEX ix_messages_text_trgm ON messages USING gin (text gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_text_trgm")
    op.execute("DROP INDEX IF EXISTS ix_contacts_search_trgm")
    op.drop_index(
        "ix_message_statuses_orphans",
        table_name="message_statuses",
        postgresql_where=sa.text("message_id IS NULL"),
    )
    op.drop_index("ix_message_statuses_message_id", table_name="message_statuses")
    op.drop_table("message_statuses")
    op.drop_index(
        "ix_message_media_pending",
        table_name="message_media",
        postgresql_where=sa.text("download_status = 'pending'"),
    )
    op.drop_table("message_media")
    op.drop_index("ix_messages_sent_at", table_name="messages")
    op.drop_index("ix_messages_conversation_sent_at", table_name="messages")
    op.drop_index("ix_messages_account_sent_at", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_webhook_events_status_received", table_name="webhook_events")
    op.drop_index(
        "ix_webhook_events_due",
        table_name="webhook_events",
        postgresql_where=sa.text("status IN ('pending', 'retry')"),
    )
    op.drop_index("ix_webhook_events_account_id", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("ix_conversations_last_message_at", table_name="conversations")
    op.drop_index("ix_conversations_contact_id", table_name="conversations")
    op.drop_index("ix_conversations_account_last_message", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index(
        "uq_accounts_provider_phone_number_id",
        table_name="whatsapp_accounts",
        postgresql_where=sa.text("phone_number_id IS NOT NULL"),
    )
    op.drop_table("whatsapp_accounts")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_contacts_last_activity_at", table_name="contacts")
    op.drop_table("contacts")
