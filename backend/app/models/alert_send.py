from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AlertSend(Base):
    """Лог одной отправки уведомления (denominator для CTR).

    Одна строка = «листинг X ушёл пользователю Y по алёрту Z». clicked_at
    проставляется один раз при первом клике через /r/{token}. discount_snapshot
    и district снимаем В МОМЕНТ отправки — на Listing они потом пересчитываются,
    а нам нужен срез на тот момент (CTR по корзинам скидки). FK — SET NULL,
    чтобы удаление алёрта/листинга/юзера не стирало историю кликов.
    """

    __tablename__ = "alert_sends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    alert_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    listing_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    discount_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    district: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    clicked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
