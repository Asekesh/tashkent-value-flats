from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

PLAN_ENUM = Enum("free", "pro", "agent", name="subscription_plan", native_enum=False)
SUBSCRIPTION_STATUS_ENUM = Enum(
    "active", "expired", "cancelled", name="subscription_status", native_enum=False
)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan: Mapped[str] = mapped_column(PLAN_ENUM, default="free", server_default="free")
    status: Mapped[str] = mapped_column(
        SUBSCRIPTION_STATUS_ENUM, default="active", server_default="active"
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
