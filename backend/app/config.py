"""Application settings, loaded from environment variables (or a local .env file).

Secrets are only ever read from the environment. Per-number provider credentials
(360dialog API keys) are NOT configured here: they are stored encrypted on each
`whatsapp_accounts` row so numbers can be added without configuration changes.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+psycopg://wa:wa@localhost:5432/wa_dashboard"
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # Dashboard auth
    jwt_secret: str = Field(default="", repr=False)
    jwt_expires_minutes: int = 480
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Fernet key used to encrypt provider API keys at rest.
    encryption_key: str = Field(default="", repr=False)

    # Public base URL of this service, used to build per-number webhook URLs.
    public_base_url: str = "http://localhost:8000"

    # Webhook authentication
    webhook_shared_secret: str = Field(default="", repr=False)
    webhook_secret_header: str = "X-Webhook-Secret"
    webhook_max_body_bytes: int = 10 * 1024 * 1024

    # 360dialog
    dialog360_api_base_url: str = "https://waba-v2.360dialog.io"
    dialog360_platform_secret: str = Field(default="", repr=False)
    dialog360_require_signature: bool = False
    dialog360_timeout_seconds: float = 30.0

    # Media storage (S3-compatible)
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "wa-media"
    s3_access_key_id: str = Field(default="", repr=False)
    s3_secret_access_key: str = Field(default="", repr=False)
    s3_server_side_encryption: str = ""  # e.g. "AES256" on AWS S3
    media_max_bytes: int = 100 * 1024 * 1024

    # Processing
    worker_poll_interval_seconds: float = 1.0
    event_max_attempts: int = 8
    media_max_attempts: int = 5
    raw_event_retention_days: int = 30

    # Analytics
    active_conversation_hours: int = 24

    # Serve the built dashboard from the API (single-image deployment).
    frontend_dist_dir: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_for_runtime(self) -> None:
        """Fail fast on missing/weak secrets outside of tests."""
        if self.app_env == "test":
            return
        problems = []
        if len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be at least 32 characters")
        if not self.encryption_key:
            problems.append(
                "ENCRYPTION_KEY is required (generate with `python -m app.cli gen-key`)"
            )
        if self.is_production:
            if len(self.webhook_shared_secret) < 24:
                problems.append(
                    "WEBHOOK_SHARED_SECRET must be at least 24 characters in production"
                )
            if not self.public_base_url.startswith("https://"):
                problems.append("PUBLIC_BASE_URL must be https:// in production")
            if self.dialog360_require_signature and not self.dialog360_platform_secret:
                problems.append("DIALOG360_REQUIRE_SIGNATURE needs DIALOG360_PLATFORM_SECRET")
        if problems:
            raise RuntimeError("Invalid configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
