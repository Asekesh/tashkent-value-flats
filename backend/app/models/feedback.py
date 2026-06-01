from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Feedback(Base):
    """Тикет обратной связи: сообщение об ошибке или пожелание от пользователя.

    Приходит двумя путями — модальное окно на сайте (source="web") и
    Telegram-бот (source="bot"). user_id может быть None (анонимная веб-отправка
    без логина); contact — снимок контакта (username / имя / tg_id) для показа
    в админке.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # "bug" | "feature"
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(8))  # "web" | "bot"
    contact: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
