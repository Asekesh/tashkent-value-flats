"""Строгая оценка рынка для одного листинга — каскад CMA.

В отличие от [market.py:build_market_index], этот эстимейтор:
- использует тот же каскад «дом → массив/ЖК → район» что и CMA-детальная;
- фильтрует по сегменту, материалу стен, этажу (близость + не смешиваем
  крайние со средними), году постройки (та же эпоха);
- результат кешируется в столбцах Listing — API читает их напрямую,
  без живого пересчёта.

Это решает проблему «Феруза vs Ц-1»: панелька на краю города больше не
сравнивается с монолитом в центре только потому, что они формально в
одном районе.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Listing
from app.services.cma import AREA_TOLERANCE, build_cma
from app.services.market import (
    MARKET_PRICE_MAX_USD_PER_M2,
    MARKET_PRICE_MIN_USD_PER_M2,
    MAX_REALISTIC_DISCOUNT_PERCENT,
)
from app.services.segmentation import is_extreme_floor


@dataclass
class ListingEstimate:
    market_price_per_m2_usd: Optional[float]
    sample_size: int
    basis: str
    confidence: str
    discount_percent: Optional[float]
    is_below_market: bool
    savings_usd: Optional[float]


def _empty(basis: str = "insufficient_data") -> ListingEstimate:
    return ListingEstimate(
        market_price_per_m2_usd=None,
        sample_size=0,
        basis=basis,
        confidence="low",
        discount_percent=None,
        is_below_market=False,
        savings_usd=None,
    )


def _confidence(sample_size: int, basis: str) -> str:
    if basis == "district_relaxed":
        # фоллбэк-режим: критерии ослаблены, доверие низкое даже при большой выборке
        return "low"
    if sample_size >= 10:
        return "high"
    if sample_size >= 5:
        return "medium"
    return "low"


def estimate_for_listing(db: Session, listing: Listing) -> ListingEstimate:
    """Оценка рынка для одного листинга. Использует каскад [build_cma]
    и переводит его статистику в Estimate с дисконтом и sanity-фильтрами."""
    settings = get_settings()
    if not listing.area_m2 or listing.area_m2 <= 0 or not listing.price_per_m2_usd:
        return _empty()

    cma = build_cma(db, listing)
    market_price = cma.stats.median_price_per_m2_usd
    sample_size = cma.stats.count

    if not market_price or not (
        MARKET_PRICE_MIN_USD_PER_M2 <= market_price <= MARKET_PRICE_MAX_USD_PER_M2
    ):
        return _empty(basis=cma.basis if cma.basis != "insufficient_data" else "insufficient_data")

    # Крайние этажи — структурно дешевле, дисконт не считаем (база
    # для них ненадёжна, мы их и из CMA-пула отдельной веткой держим).
    if is_extreme_floor(listing.floor, listing.total_floors):
        return ListingEstimate(
            market_price_per_m2_usd=round(market_price, 2),
            sample_size=sample_size,
            basis=cma.basis,
            confidence=_confidence(sample_size, cma.basis),
            discount_percent=None,
            is_below_market=False,
            savings_usd=None,
        )

    raw_discount = (1 - listing.price_per_m2_usd / market_price) * 100
    if raw_discount > MAX_REALISTIC_DISCOUNT_PERCENT:
        # Дисконт > 30% — скам, опечатка или другая категория. Не показываем
        # фейковый «-50%» — это разрушает доверие к продукту.
        return ListingEstimate(
            market_price_per_m2_usd=round(market_price, 2),
            sample_size=sample_size,
            basis=cma.basis,
            confidence=_confidence(sample_size, cma.basis),
            discount_percent=None,
            is_below_market=False,
            savings_usd=None,
        )

    discount = round(raw_discount, 2)
    threshold = settings.below_market_threshold * 100
    is_below = discount >= threshold
    savings = round((market_price - listing.price_per_m2_usd) * listing.area_m2, 2)

    return ListingEstimate(
        market_price_per_m2_usd=round(market_price, 2),
        sample_size=sample_size,
        basis=cma.basis,
        confidence=_confidence(sample_size, cma.basis),
        discount_percent=discount,
        is_below_market=is_below,
        savings_usd=savings,
    )


def apply_estimate(listing: Listing, estimate: ListingEstimate) -> None:
    """Записать оценку в столбцы листинга. Коммит — на стороне вызывающего."""
    listing.market_price_per_m2_usd = estimate.market_price_per_m2_usd
    listing.market_basis = estimate.basis
    listing.market_sample_size = estimate.sample_size
    listing.market_confidence = estimate.confidence
    listing.discount_percent = estimate.discount_percent
    listing.is_below_market = estimate.is_below_market
    listing.savings_usd = estimate.savings_usd
    listing.market_calculated_at = datetime.utcnow()


def compute_and_store(db: Session, listing: Listing) -> ListingEstimate:
    """Посчитать и записать оценку для одного листинга (без коммита)."""
    estimate = estimate_for_listing(db, listing)
    apply_estimate(listing, estimate)
    return estimate


def recompute_all(
    db: Session,
    *,
    limit: Optional[int] = None,
    on_progress: Optional[callable] = None,
) -> int:
    """Батч-пересчёт оценок для всех активных листингов.

    Возвращает количество обработанных. Коммит делается батчами по 500
    чтобы не держать большую транзакцию открытой и периодически отдавать
    данные потребителям.
    """
    stmt = select(Listing).where(Listing.status == "active")
    if limit:
        stmt = stmt.limit(limit)
    listings: Iterable[Listing] = db.scalars(stmt).all()

    processed = 0
    batch_size = 500
    for listing in listings:
        compute_and_store(db, listing)
        processed += 1
        if processed % batch_size == 0:
            db.commit()
            if on_progress:
                on_progress(processed)
    db.commit()
    if on_progress:
        on_progress(processed)
    return processed
