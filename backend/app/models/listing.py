from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_listing_source_id"),
        # Составной B-tree под bbox-запросы карты (см. миграцию 0018). Объявлен здесь,
        # чтобы create_all (тесты/свежий dev) совпадал с прод-схемой из миграции.
        Index("ix_listings_lat_lng", "lat", "lng"),
    )

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
    seller_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)  # id продавца у площадки (Uybor userId, OLX user.id)
    is_business: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # площадка пометила бизнес-аккаунт (OLX isBusiness) → агент; NULL=неизвестно
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

    # --- Раздел «Аренда». Для продажи deal_type='sale' (дефолт), остальное NULL,
    #     поэтому существующие строки и старый парсер продажи не затрагиваются.
    #     seller_type НЕ дублируем — колонка уже объявлена выше. ---
    deal_type: Mapped[str] = mapped_column(String(16), default="sale", server_default="sale", index=True)
    price_period: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # 'month' | 'day'; NULL для продажи
    is_furnished: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # фильтр аренды; NULL = неизвестно
    commission_pct: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)  # NULL=неизвестно, 0=без комиссии
    residential_complex_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("residential_complex.id", ondelete="SET NULL"), nullable=True, index=True
    )
    deposit: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)  # опционально
    utilities_included: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # опционально

    # --- Гео для карты (миграция 0018). NULL = координат нет (старые строки,
    #     Realt24); наливаются при повторном проходе через парсер.
    #     coords_precision: 'exact' (Uybor) | 'approx' (OLX, размытие ~2-5 км) | NULL. ---
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coords_precision: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    # Справочник ЖК. lazy="select": деталь-эндпоинт читает имя без явного eager-load;
    # в списке листингов грузим через selectinload, чтобы не ловить N+1.
    residential_complex: Mapped[Optional["ResidentialComplex"]] = relationship(lazy="select")


class ResidentialComplex(Base):
    """Справочник ЖК. Парсер апсертит по match_key (нормализованный ключ), чтобы
    варианты написания одного ЖК схлопывались в одну строку, а не плодили дубли."""

    __tablename__ = "residential_complex"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255))  # каноничное имя для показа
    match_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)  # ключ склейки
    district: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
