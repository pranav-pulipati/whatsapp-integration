"""Object storage for media. PostgreSQL only stores the key + metadata."""

from functools import lru_cache
from typing import Protocol

import boto3
from botocore.config import Config

from app.config import get_settings


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str | None) -> None: ...

    def get(self, key: str) -> tuple[bytes, str | None]: ...


class S3Storage:
    def __init__(self) -> None:
        s = get_settings()
        self.bucket = s.s3_bucket
        self.sse = s.s3_server_side_encryption
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key_id or None,
            aws_secret_access_key=s.s3_secret_access_key or None,
            config=Config(retries={"max_attempts": 3, "mode": "standard"}),
        )

    def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist (local dev). In production the
        bucket is pre-created and the key usually lacks CreateBucket rights."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes, content_type: str | None) -> None:
        extra = {"ServerSideEncryption": self.sse} if self.sse else {}
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
            **extra,
        )

    def get(self, key: str) -> tuple[bytes, str | None]:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read(), obj.get("ContentType")


class InMemoryStorage:
    """Used by tests."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}

    def put(self, key: str, data: bytes, content_type: str | None) -> None:
        self.objects[key] = (data, content_type)

    def get(self, key: str) -> tuple[bytes, str | None]:
        return self.objects[key]


@lru_cache
def get_storage() -> Storage:
    return S3Storage()
