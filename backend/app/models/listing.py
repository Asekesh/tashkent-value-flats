from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_listing_source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[str] = mapped_column(String(160), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(12))
    price_usd: Mapped[float] = mapped_column(Float, index=True)
    area_m2: Mapped[float] = mapped_column(Float, index=True)
    price_per_m2_usd: Mapped[float] = mapped_column(Float, index=True)
    rooms: Mapped[int] = mapped_column(Integer, index=True)
    floor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_floors: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    district: Mapped[str] = mapped_column(String(120), index=True)
    address_raw: Mapped[str] = mapped_column(Text)
    building_key: Mapped[Optional[str]] = mapped_column(String(220), nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    photos: Mapped[str] = mapped_column(Text, default="[]")
    seller_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    duplicate_group_key: Mapped[str] = mapped_column(String(255), index=True)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=1)
    source_urls: Mapped[str] = mapped_column(Text, default="[]")
    # Кешированная оценка рынка. Обновляется в upsert и в ночном rebuild;
    # API читает эти столбцы напрямую вместо живого пересчёта (11700 листингов
    # × один SELECT — слишком долго на каждый запрос).
    market_price_per_m2_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_basis: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    market_sample_size: Mapped[int] = mapped_column(Integer, default=0)
    market_confidence: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    discount_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    is_below_market: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    savings_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_calculated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
