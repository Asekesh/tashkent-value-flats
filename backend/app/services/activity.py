"""Запись факта дневной активности пользователя (бот + веб) → user_activity."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import UserActivity


def mark_active(db: Session, user_id: int, when: Optional[datetime] = None) -> None:
    """Отметить пользователя активным в день `when` (UTC, по умолчанию сейчас).

    ON CONFLICT DO NOTHING: на (user_id, day) держим максимум одну строку, при
    повторных касаниях за день — no-op. Не коммитит — это делает вызывающий код
    в своей транзакции. При неизвестном диалекте тихо пропускаем (DAU — не
    критичная для пути запроса метрика, ронять веб-логин из-за неё нельзя).
    """
    day = (when or datetime.utcnow()).date()
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        return
    stmt = (
        insert(UserActivity)
        .values(user_id=user_id, day=day)
        .on_conflict_do_nothing(index_elements=["user_id", "day"])
    )
    db.execute(stmt)
