"""Test harness: a real PostgreSQL database (TEST_DATABASE_URL), migrated once per
session and truncated between tests. No 360dialog credentials are needed."""

import os

from cryptography.fernet import Fernet

os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", "postgresql+psycopg://wa:wa@localhost:55432/wa_test"
        ),
        "JWT_SECRET": "test-jwt-secret-" + "x" * 32,
        "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "WEBHOOK_SHARED_SECRET": "test-webhook-shared-secret",
        "DIALOG360_PLATFORM_SECRET": "",
        "CORS_ORIGINS": "",
        "FRONTEND_DIST_DIR": "",
        "LOG_LEVEL": "WARNING",
    }
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import get_engine, session_scope  # noqa: E402
from app.models import WhatsAppAccount  # noqa: E402
from app.ratelimit import login_limiter, webhook_limiter  # noqa: E402
from app.security import encrypt_secret, generate_webhook_token  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))
WEBHOOK_HEADERS = {"X-Webhook-Secret": "test-webhook-shared-secret"}


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _clean():
    yield
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE webhook_events, message_media, message_statuses, messages, "
                "conversations, contacts, whatsapp_accounts, users RESTART IDENTITY CASCADE"
            )
        )
    login_limiter.reset()
    webhook_limiter.reset()


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def make_account(
    display: str = "15550001111",
    phone_number_id: str | None = "109876543210001",
    name: str = "Sales — Bengaluru",
    api_key: str | None = "test-api-key",
) -> WhatsAppAccount:
    with session_scope() as db:
        acc = WhatsAppAccount(
            provider="360dialog",
            display_phone_number=display,
            phone_number_id=phone_number_id,
            name=name,
            status="pending",
            webhook_token=generate_webhook_token(),
            api_key_encrypted=encrypt_secret(api_key) if api_key else None,
        )
        db.add(acc)
        db.flush()
        db.expunge(acc)
    return acc


@pytest.fixture
def account() -> WhatsAppAccount:
    return make_account()
