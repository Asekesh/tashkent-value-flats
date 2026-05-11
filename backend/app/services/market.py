from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Listing
from app.services.normalization import median_price


@dataclass
class Estimate:
    market_price_per_m2_usd: float | None
    sample_size: int
    basis: str
    confidence: str
    discount_percent: float | None
    is_below_market: bool
    savings_usd: float | None


def estimate_market(
    db: Session,
    *,
    district: str,
    rooms: int,
    area_m2: float,
    building_key: str | None = None,
    listing_price_per_m2: float | None = None,
    exclude_listing_id: int | None = None,
) -> Estimate:
    candidates, basis, confidence = _building_candidates(db, building_key, rooms, exclude_listing_id)

    # Если есть 2+ объявления в том же ЖК — считаем простое среднее по ЖК
    market_price = None
    if len(candidates) >= 2:
        prices = [item.price_per_m2_usd for item in candidates if item.price_per_m2_usd]
        if prices:
            market_price = round(sum(prices) / len(prices), 2)
            basis = "building"
            confidence = "high"
    else:
        # fallback на существующую логику (district +/- area, затем district by rooms)
        if len(candidates) < 3:
            candidates, basis, confidence = _district_area_candidates(db, district, rooms, area_m2, exclude_listing_id)
        if len(candidates) < 3:
            candidates, basis, confidence = _district_room_candidates(db, district, rooms, exclude_listing_id)

        market_price = median_price([item.price_per_m2_usd for item in candidates])

    discount = None
    savings = None
    is_below_market = False
    if market_price and listing_price_per_m2:
        if market_price != 0:
            discount = round((1 - listing_price_per_m2 / market_price) * 100, 2)
        else:
            discount = None
        if discount is not None:
            threshold = get_settings().below_market_threshold * 100
            is_below_market = discount >= threshold
        if listing_price_per_m2 and area_m2 and market_price is not None:
            savings = round((market_price - listing_price_per_m2) * area_m2, 2)
    if len(candidates) < 3:
        confidence = "low"
        basis = "insufficient_data"

    return Estimate(
        market_price_per_m2_usd=market_price,
        sample_size=len(candidates),
        basis=basis,
        confidence=confidence,
        discount_percent=discount,
        is_below_market=is_below_market,
        savings_usd=savings,
    )


def _building_candidates(db: Session, building_key: str | None, rooms: int, exclude_id: int | None) -> tuple[list[Listing], str, str]:
    if not building_key:
        return [], "building", "low"
    settings = get_settings()
    stmt = select(Listing).where(
        Listing.status == "active",
        Listing.price_usd >= settings.min_listing_price_usd,
        Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
        Listing.building_key == building_key,
        Listing.rooms == rooms,
    )
    if exclude_id:
        stmt = stmt.where(Listing.id != exclude_id)
    return list(db.scalars(stmt).all()), "building", "high"


def _district_area_candidates(db: Session, district: str, rooms: int, area_m2: float, exclude_id: int | None) -> tuple[list[Listing], str, str]:
    settings = get_settings()
    min_area = area_m2 * 0.85
    max_area = area_m2 * 1.15
    stmt = select(Listing).where(
        Listing.status == "active",
        Listing.price_usd >= settings.min_listing_price_usd,
        Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
        Listing.district == district,
        Listing.rooms == rooms,
        Listing.area_m2 >= min_area,
        Listing.area_m2 <= max_area,
    )
    if exclude_id:
        stmt = stmt.where(Listing.id != exclude_id)
    return list(db.scalars(stmt).all()), "district_rooms_area", "medium"


def _district_room_candidates(db: Session, district: str, rooms: int, exclude_id: int | None) -> tuple[list[Listing], str, str]:
    settings = get_settings()
    stmt = select(Listing).where(
        Listing.status == "active",
        Listing.price_usd >= settings.min_listing_price_usd,
        Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
        Listing.district == district,
        Listing.rooms == rooms,
    )
    if exclude_id:
        stmt = stmt.where(Listing.id != exclude_id)
    return list(db.scalars(stmt).all()), "district_rooms", "low"
