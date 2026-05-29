from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Alert(Base):
    """Подписка пользователя на новые листинги под заданный фильтр.

    Поля districts/rooms/sources — CSV строки (а не JSON), потому что
    SQLite в проде это устроит без особых хлопот и проще писать matcher.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    districts: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rooms: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    price_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ppm_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ppm_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    area_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    area_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sources: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
