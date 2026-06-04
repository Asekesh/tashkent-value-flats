"""User lookup / creation from Telegram login payloads."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import LoginEvent, User
from app.services.activity import mark_active


def get_or_create_user(db: Session, tg: dict[str, str]) -> User:
    """Find a user by telegram_id or create one from the widget payload.

    Updates profile fields + last_login_at, and promotes the user to admin
    when their telegram_id is listed in ADMIN_TELEGRAM_IDS.
    """
    telegram_id = int(tg["id"])
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(telegram_id=telegram_id)
        db.add(user)

    user.username = tg.get("username") or user.username
    user.first_name = tg.get("first_name") or user.first_name
    user.last_name = tg.get("last_name") or user.last_name
    user.photo_url = tg.get("photo_url") or user.photo_url
    now = datetime.utcnow()
    user.last_login_at = now
    # Унифицируем сенсор активности: веб-логин — тоже «касание», иначе
    # веб-юзеры были бы невидимы в last_seen_at / ретеншне (он писался лишь
    # в боте). Веб-логин = активность дня → user_activity.
    user.last_seen_at = now

    if telegram_id in get_settings().admin_telegram_id_set:
        user.role = "admin"

    db.flush()  # нужен user.id (для новых юзеров) до отметки активности
    mark_active(db, user.id, now)
    return user


def record_login_event(db: Session, user: User, ip: Optional[str]) -> None:
    db.add(LoginEvent(user_id=user.id, ip=ip))
