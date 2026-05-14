from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import User

BOT_TOKEN = "123456:test-bot-token"


def _signed_payload(**overrides) -> dict[str, str]:
    payload = {"id": "1001", "first_name": "Admin", "auth_date": str(int(time.time()))}
    payload.update(overrides)
    pairs = [f"{k}={payload[k]}" for k in sorted(payload) if k != "hash"]
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    payload["hash"] = hmac.new(secret, "\n".join(pairs).encode(), hashlib.sha256).hexdigest()
    return payload


def _login(client, telegram_id: str) -> None:
    client.get(
        "/auth/telegram/callback",
        params=_signed_payload(id=telegram_id),
        follow_redirects=False,
    )


@pytest.fixture()
def admin_env(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_bot_token", BOT_TOKEN)
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "admin_telegram_ids", "1001")
    return settings


def test_admin_requires_auth(client):
    assert client.get("/admin", follow_redirects=False).status_code == 403


def test_admin_forbidden_for_regular_user(client, admin_env):
    _login(client, "2002")  # not in ADMIN_TELEGRAM_IDS -> role=user
    assert client.get("/admin", follow_redirects=False).status_code == 403


def test_admin_dashboard_ok_for_admin(client, admin_env):
    _login(client, "1001")
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Дашборд" in resp.text
    assert "Всего пользователей" in resp.text


def test_admin_users_list_and_search(client, admin_env, db_session):
    db_session.add(User(telegram_id=3003, username="bob"))
    db_session.commit()
    _login(client, "1001")
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    assert "3003" in resp.text
    # search by telegram_id
    resp = client.get("/admin/users", params={"q": "3003"})
    assert "3003" in resp.text and resp.text.count("<tr>") >= 1


def test_admin_can_change_role_and_account_type(client, admin_env, db_session):
    db_session.add(User(telegram_id=4004))
    db_session.commit()
    _login(client, "1001")
    target = db_session.scalar(select(User).where(User.telegram_id == 4004))
    assert target.role == "user" and target.account_type == "individual"

    client.post(f"/admin/users/{target.id}/role", data={"role": "admin"}, follow_redirects=False)
    client.post(
        f"/admin/users/{target.id}/account-type",
        data={"account_type": "agent"},
        follow_redirects=False,
    )
    db_session.expire_all()
    target = db_session.get(User, target.id)
    assert target.role == "admin" and target.account_type == "agent"
