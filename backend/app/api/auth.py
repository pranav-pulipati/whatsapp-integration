import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.schemas import LoginRequest, TokenOut, UserOut
from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.ratelimit import login_limiter
from app.security import create_access_token, hash_password, verify_password

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the email is unknown, so response time doesn't reveal accounts.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/login", response_model=TokenOut, summary="Exchange email + password for a token")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    client_ip = request.client.host if request.client else "unknown"
    if not login_limiter.allow(f"{client_ip}:{body.email.lower()}"):
        raise ApiError(429, "rate_limited", "Too many login attempts, try again in a minute")

    user = db.execute(
        select(User).where(func.lower(User.email) == body.email.lower())
    ).scalar_one_or_none()
    valid = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if not user or not valid or not user.is_active:
        log.info("login failed", extra={"ctx": {"ip": client_ip}})
        raise ApiError(401, "invalid_credentials", "Invalid email or password")

    user.last_login_at = datetime.now(UTC)
    db.commit()
    token, expires = create_access_token(user.id, user.role)
    return TokenOut(access_token=token, expires_at=expires, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="Current user")
def me(user: User = Depends(current_user)) -> User:
    return user
