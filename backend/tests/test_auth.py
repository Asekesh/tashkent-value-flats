from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from sqlalchemy import select

from app.auth.security import verify_telegram_auth
from app.core.config import get_settings
from app.models import LoginEvent, User

BOT_TOKEN = "123456:test-bot-token"


def _signed_payload(**overrides) -> dict[str, str]:
    payload = {
        "id": "777",
        "first_name": "Test",
        "username": "tester",
        "auth_date": str(int(time.time())),
    }
    payload.update(overrides)
    pairs = [f"{k}={payload[k]}" for k in sorted(payload) if k != "hash"]
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    payload["hash"] = hmac.new(
        secret, "\n".join(pairs).encode(), hashlib.sha256
    ).hexdigest()
    return payload


def test_verify_telegram_auth_valid():
    assert verify_telegram_auth(_signed_payload(), BOT_TOKEN) is True


def test_verify_telegram_auth_bad_hash():
    payload = _signed_payload()
    payload["hash"] = "deadbeef"
    assert verify_telegram_auth(payload, BOT_TOKEN) is False


def test_verify_telegram_auth_stale_auth_date():
    stale = str(int(time.time()) - 25 * 3600)
    assert verify_telegram_auth(_signed_payload(auth_date=stale), BOT_TOKEN) is False


@pytest.fixture()
def auth_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "admin_telegram_ids", "")
    return settings


def test_callback_creates_user_and_session(client, db_session, auth_settings):
    resp = client.get(
        "/auth/telegram/callback",
        params=_signed_payload(id="555", username="alice"),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert get_settings().jwt_cookie_name in resp.cookies

    user = db_session.scalar(select(User).where(User.telegram_id == 555))
    assert user is not None and user.username == "alice"
    assert user.role == "user"
    assert db_session.scalar(select(LoginEvent).where(LoginEvent.user_id == user.id))

    me = client.get("/auth/me").json()
    assert me["authenticated"] is True and me["telegram_id"] == 555


def test_callback_rejects_bad_signature(client, auth_settings):
    payload = _signed_payload(id="556")
    payload["hash"] = "00"
    resp = client.get("/auth/telegram/callback", params=payload, follow_redirects=False)
    assert resp.status_code == 403


def test_admin_promotion_via_env(client, db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "admin_telegram_ids", "999")
    client.get(
        "/auth/telegram/callback",
        params=_signed_payload(id="999"),
        follow_redirects=False,
    )
    user = db_session.scalar(select(User).where(User.telegram_id == 999))
    assert user.role == "admin"


def test_logout_clears_cookie(client, auth_settings):
    client.get(
        "/auth/telegram/callback",
        params=_signed_payload(id="600"),
        follow_redirects=False,
    )
    assert client.get("/auth/me").json()["authenticated"] is True
    client.get("/auth/logout", follow_redirects=False)
    assert client.get("/auth/me").json()["authenticated"] is False


def test_public_listings_work_without_auth(client):
    assert client.get("/api/listings").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}
