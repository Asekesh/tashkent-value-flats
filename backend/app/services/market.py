from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Listing


@dataclass
class Estimate:
    market_price_per_m2_usd: float | None
    sample_size: int
    basis: str
    confidence: str
    discount_percent: float | None
    is_below_market: bool
    savings_usd: float | None


@dataclass
class MarketIndex:
    """Предрассчитанные средние/медианы по всей активной базе.

    Используется и `/listings`, и `/listings/stats`, чтобы числа на дашборде и
    в списке считались по одной формуле.
    """

    building: dict[str, tuple[float, int]] = field(default_factory=dict)
    district_rooms: dict[tuple[str, int], tuple[float, int]] = field(default_factory=dict)


def build_market_index(db: Session) -> MarketIndex:
    settings = get_settings()
    rows = db.execute(
        select(
            Listing.district,
            Listing.rooms,
            Listing.building_key,
            Listing.price_per_m2_usd,
        ).where(
            Listing.status == "active",
            Listing.price_usd >= settings.min_listing_price_usd,
            Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
        )
    ).all()
    building_groups: dict[str, list[float]] = defaultdict(list)
    district_room_groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in rows:
        if row.price_per_m2_usd is None:
            continue
        if row.building_key:
            building_groups[row.building_key].append(row.price_per_m2_usd)
        district_room_groups[(row.district, row.rooms)].append(row.price_per_m2_usd)
    building = {
        key: (sum(values) / len(values), len(values))
        for key, values in building_groups.items()
        if len(values) >= 2
    }
    district_rooms = {
        key: (float(median(values)), len(values))
        for key, values in district_room_groups.items()
        if len(values) >= 3
    }
    return MarketIndex(building=building, district_rooms=district_rooms)


def estimate_from_index(
    index: MarketIndex,
    *,
    building_key: str | None,
    district: str,
    rooms: int,
    area_m2: float | None,
    listing_price_per_m2: float | None,
) -> Estimate:
    market_price: float | None = None
    sample_size = 0
    basis = "insufficient_data"
    confidence = "low"

    if building_key and building_key in index.building:
        avg, count = index.building[building_key]
        market_price = round(avg, 2)
        sample_size = count
        basis = "building"
        confidence = "high"
    elif (district, rooms) in index.district_rooms:
        med, count = index.district_rooms[(district, rooms)]
        market_price = round(med, 2)
        sample_size = count
        basis = "district_rooms"
        confidence = "medium" if count >= 5 else "low"

    discount: float | None = None
    savings: float | None = None
    is_below = False
    if market_price and listing_price_per_m2 and market_price > 0:
        discount = round((1 - listing_price_per_m2 / market_price) * 100, 2)
        threshold = get_settings().below_market_threshold * 100
        is_below = discount >= threshold
        if area_m2:
            savings = round((market_price - listing_price_per_m2) * area_m2, 2)

    return Estimate(
        market_price_per_m2_usd=market_price,
        sample_size=sample_size,
        basis=basis,
        confidence=confidence,
        discount_percent=discount,
        is_below_market=is_below,
        savings_usd=savings,
    )


def estimate_market(
    db: Session,
    *,
    district: str,
    rooms: int,
    area_m2: float,
    building_key: str | None = None,
    listing_price_per_m2: float | None = None,
    exclude_listing_id: int | None = None,  # noqa: ARG001 — оставлено для совместимости вызовов
) -> Estimate:
    """Оценка для одного объявления — использует тот же индекс, что и листинг/статистика."""
    index = build_market_index(db)
    return estimate_from_index(
        index,
        building_key=building_key,
        district=district,
        rooms=rooms,
        area_m2=area_m2,
        listing_price_per_m2=listing_price_per_m2,
    )
