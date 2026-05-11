from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Listing


AREA_TOLERANCE = 0.15
MAX_ANALOGS = 20


@dataclass
class CmaAnalog:
    id: int
    source: str
    url: str
    title: str
    price_usd: float
    area_m2: float
    price_per_m2_usd: float
    rooms: int
    floor: Optional[int]
    district: str
    address_raw: str
    seen_at: str


@dataclass
class CmaStats:
    count: int
    avg_price_per_m2_usd: Optional[float]
    median_price_per_m2_usd: Optional[float]
    min_price_per_m2_usd: Optional[float]
    max_price_per_m2_usd: Optional[float]
    avg_price_usd: Optional[float]


@dataclass
class CmaResult:
    subject: CmaAnalog
    basis: str  # "building" | "district"
    basis_label: str
    area_tolerance_percent: float
    stats: CmaStats
    subject_vs_market_percent: Optional[float]
    analogs: list[CmaAnalog]


def _to_analog(listing: Listing) -> CmaAnalog:
    return CmaAnalog(
        id=listing.id,
        source=listing.source,
        url=listing.url,
        title=listing.title,
        price_usd=listing.price_usd,
        area_m2=listing.area_m2,
        price_per_m2_usd=listing.price_per_m2_usd,
        rooms=listing.rooms,
        floor=listing.floor,
        district=listing.district,
        address_raw=listing.address_raw,
        seen_at=listing.seen_at.isoformat() if listing.seen_at else "",
    )


def _stats(analogs: list[CmaAnalog]) -> CmaStats:
    if not analogs:
        return CmaStats(0, None, None, None, None, None)
    ppm = [a.price_per_m2_usd for a in analogs if a.price_per_m2_usd]
    prices = [a.price_usd for a in analogs if a.price_usd]
    return CmaStats(
        count=len(analogs),
        avg_price_per_m2_usd=round(sum(ppm) / len(ppm), 2) if ppm else None,
        median_price_per_m2_usd=round(float(median(ppm)), 2) if ppm else None,
        min_price_per_m2_usd=round(min(ppm), 2) if ppm else None,
        max_price_per_m2_usd=round(max(ppm), 2) if ppm else None,
        avg_price_usd=round(sum(prices) / len(prices), 2) if prices else None,
    )


def build_cma(db: Session, listing: Listing) -> CmaResult:
    settings = get_settings()
    min_area = listing.area_m2 * (1 - AREA_TOLERANCE)
    max_area = listing.area_m2 * (1 + AREA_TOLERANCE)

    base_filters = (
        Listing.status == "active",
        Listing.price_usd >= settings.min_listing_price_usd,
        Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
        Listing.rooms == listing.rooms,
        Listing.area_m2 >= min_area,
        Listing.area_m2 <= max_area,
        Listing.id != listing.id,
    )

    basis = "district"
    basis_label = f"район {listing.district}, {listing.rooms}-комн., площадь ±15%"
    candidates: list[Listing] = []

    if listing.building_key:
        stmt = select(Listing).where(*base_filters, Listing.building_key == listing.building_key)
        candidates = list(db.scalars(stmt).all())
        if candidates:
            basis = "building"
            basis_label = f"тот же дом ({listing.address_raw or listing.district}), {listing.rooms}-комн., площадь ±15%"

    if not candidates:
        stmt = select(Listing).where(*base_filters, Listing.district == listing.district)
        candidates = list(db.scalars(stmt).all())

    candidates.sort(key=lambda c: abs(c.area_m2 - listing.area_m2))
    candidates = candidates[:MAX_ANALOGS]

    analogs = [_to_analog(c) for c in candidates]
    stats = _stats(analogs)
    diff = None
    if stats.median_price_per_m2_usd and listing.price_per_m2_usd:
        diff = round((listing.price_per_m2_usd / stats.median_price_per_m2_usd - 1) * 100, 2)

    return CmaResult(
        subject=_to_analog(listing),
        basis=basis,
        basis_label=basis_label,
        area_tolerance_percent=AREA_TOLERANCE * 100,
        stats=stats,
        subject_vs_market_percent=diff,
        analogs=analogs,
    )
