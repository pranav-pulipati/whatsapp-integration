from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise ApiError(401, "unauthorized", "Authentication required")
    try:
        claims = decode_access_token(creds.credentials)
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise ApiError(401, "unauthorized", "Invalid or expired session") from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "unauthorized", "Invalid or expired session")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "forbidden", "Admin role required")
    return user


@dataclass
class Page:
    limit: int
    offset: int


def pagination(
    limit: int = Query(25, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Items to skip"),
) -> Page:
    return Page(limit=limit, offset=offset)


def parse_sort(value: str | None, allowed: dict, default: str):
    """`sort=-last_message_at` → ORDER BY last_message_at DESC (allow-listed)."""
    value = value or default
    desc = value.startswith("-")
    key = value.lstrip("-")
    if key not in allowed:
        raise ApiError(
            422,
            "validation_error",
            f"Invalid sort field '{key}'",
            {"allowed": sorted(allowed)},
        )
    col = allowed[key]
    return col.desc().nulls_last() if desc else col.asc().nulls_last()


def active_cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(hours=get_settings().active_conversation_hours)
