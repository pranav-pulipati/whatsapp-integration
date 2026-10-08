"""Passwords, JWT sessions, secret encryption and constant-time comparisons."""

import hmac
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_hasher = PasswordHasher()
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_access_token(user_id: int, role: str) -> tuple[str, datetime]:
    s = get_settings()
    expires = datetime.now(UTC) + timedelta(minutes=s.jwt_expires_minutes)
    token = jwt.encode(
        {"sub": str(user_id), "role": role, "exp": expires},
        s.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    return token, expires


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALGORITHM])


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is not configured")
    return Fernet(key.encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Stored secret cannot be decrypted (wrong ENCRYPTION_KEY?)") from exc


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode()


def generate_webhook_token() -> str:
    return secrets.token_urlsafe(32)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
