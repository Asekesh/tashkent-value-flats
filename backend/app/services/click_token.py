"""Подписанные токены для /r/{token} — трекинг кликов по алёртам.

Стейтлес: токен = base64url(send_id).base64url(HMAC-SHA256(secret, send_id)[:10]).
Юзер не может подделать/перебрать чужой клик. Секрет переиспользуем из JWT —
новых env не нужно. stdlib, без зависимостей.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from app.core.config import get_settings

_SIG_LEN = 10


def _secret() -> bytes:
    return get_settings().jwt_secret.encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_send(send_id: int) -> str:
    payload = str(send_id).encode()
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()[:_SIG_LEN]
    return f"{_b64(payload)}.{_b64(sig)}"


def unsign_send(token: str) -> int | None:
    """Вернуть send_id, если подпись валидна, иначе None."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _unb64(payload_b64)
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()[:_SIG_LEN]
        if not hmac.compare_digest(expected, _unb64(sig_b64)):
            return None
        return int(payload.decode())
    except (ValueError, TypeError):
        return None
