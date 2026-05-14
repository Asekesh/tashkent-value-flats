"""Telegram Login Widget signature checks and JWT session tokens."""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from app.core.config import get_settings

# Telegram Login Widget fields that take part in the signature.
TELEGRAM_AUTH_FIELDS = (
    "auth_date",
    "first_name",
    "id",
    "last_name",
    "photo_url",
    "username",
)
AUTH_DATE_MAX_AGE_SECONDS = 24 * 60 * 60


def verify_telegram_auth(params: dict[str, str], bot_token: str) -> bool:
    """Validate the `hash` produced by the Telegram Login Widget.

    secret_key = SHA256(bot_token); hash = HMAC-SHA256(data_check_string).
    Also rejects payloads whose auth_date is older than 24h.
    """
    received_hash = params.get("hash")
    if not received_hash or not bot_token:
        return False

    pairs = [
        f"{key}={params[key]}"
        for key in sorted(params)
        if key != "hash" and params.get(key) not in (None, "")
    ]
    data_check_string = "\n".join(pairs)

    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return False

    try:
        auth_date = int(params.get("auth_date", "0"))
    except (TypeError, ValueError):
        return False
    if auth_date <= 0 or (time.time() - auth_date) > AUTH_DATE_MAX_AGE_SECONDS:
        return False

    return True


def create_session_token(user_id: int, telegram_id: int, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tg": telegram_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_session_token(token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
