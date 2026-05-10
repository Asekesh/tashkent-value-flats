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
    if len(candidates) < 3:
        candidates, basis, confidence = _district_area_candidates(db, district, rooms, area_m2, exclude_listing_id)
    if len(candidates) < 3:
        candidates, basis, confidence = _district_room_candidates(db, district, rooms, exclude_listing_id)

    market_price = median_price([item.price_per_m2_usd for item in candidates])
    discount = None
    is_below_market = False
    if market_price and listing_price_per_m2:
        discount = round((market_price - listing_price_per_m2) / market_price * 100, 2)
        threshold = get_settings().below_market_threshold * 100
        is_below_market = discount >= threshold
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
    )


def _building_candidates(db: Session, building_key: str | None, rooms: int, exclude_id: int | None) -> tuple[list[Listing], str, str]:
    if not building_key:
        return [], "building", "low"
    stmt = select(Listing).where(
        Listing.status == "active",
        Listing.building_key == building_key,
        Listing.rooms == rooms,
    )
    if exclude_id:
        stmt = stmt.where(Listing.id != exclude_id)
    return list(db.scalars(stmt).all()), "building", "high"


def _district_area_candidates(db: Session, district: str, rooms: int, area_m2: float, exclude_id: int | None) -> tuple[list[Listing], str, str]:
    min_area = area_m2 * 0.85
    max_area = area_m2 * 1.15
    stmt = select(Listing).where(
        Listing.status == "active",
        Listing.district == district,
        Listing.rooms == rooms,
        Listing.area_m2 >= min_area,
        Listing.area_m2 <= max_area,
    )
    if exclude_id:
        stmt = stmt.where(Listing.id != exclude_id)
    return list(db.scalars(stmt).all()), "district_rooms_area", "medium"


def _district_room_candidates(db: Session, district: str, rooms: int, exclude_id: int | None) -> tuple[list[Listing], str, str]:
    stmt = select(Listing).where(
        Listing.status == "active",
        Listing.district == district,
        Listing.rooms == rooms,
    )
    if exclude_id:
        stmt = stmt.where(Listing.id != exclude_id)
    return list(db.scalars(stmt).all()), "district_rooms", "low"
