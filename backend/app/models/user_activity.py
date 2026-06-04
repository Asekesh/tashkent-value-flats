from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserActivity(Base):
    """Один день активности пользователя = одна строка.

    last_seen_at хранит только последнюю точку — историю по ней не построить.
    Эта таблица копит факт «юзер был активен в день D» (бот ИЛИ веб-логин),
    что и даёт честный ретеншн-треугольник и единый DAU/WAU/MAU. Композитный
    PK (user_id, day) сам гарантирует «не больше одной строки на день».
    Наполняется с момента внедрения — ретроспективу восстановить нельзя.
    """

    __tablename__ = "user_activity"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
