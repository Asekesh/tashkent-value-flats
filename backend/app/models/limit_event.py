from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class LimitEvent(Base):
    """Лог момента, когда пользователь упёрся в лимит тарифа.

    Не блокируем — просто фиксируем спрос. Готовый тёплый лид-лист на платный
    тариф: кто чаще упирается, тот первый кандидат на конверсию. event_type —
    что именно ограничило ('alert_cap', позже 'district_uncovered' и т.п.).
    """

    __tablename__ = "limit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    plan: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
