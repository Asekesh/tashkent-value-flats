from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import Listing
from app.schemas.listing import ListingOut, ListingsPage, MarketEstimate
from app.services.listings import count_listings, listing_to_dict
from app.services.market import estimate_market

router = APIRouter(prefix="/api", tags=["listings"])


@router.get("/listings", response_model=ListingsPage)
def get_listings(
    db: Session = Depends(get_db),
    district: Optional[str] = None,
    rooms: Optional[int] = None,
    area_min: Optional[float] = None,
    area_max: Optional[float] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    ppm_min: Optional[float] = None,
    ppm_max: Optional[float] = None,
    discount_min: Optional[float] = None,
    source: Optional[str] = None,
    sort: Literal["discount", "price_per_m2", "fresh", "price"] = "discount",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ListingsPage:
    settings = get_settings()
    stmt = select(Listing).where(
        Listing.status == "active",
        Listing.price_usd >= settings.min_listing_price_usd,
        Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
    )
    if district:
        stmt = stmt.where(Listing.district == district)
    if rooms:
        stmt = stmt.where(Listing.rooms == rooms)
    if area_min is not None:
        stmt = stmt.where(Listing.area_m2 >= area_min)
    if area_max is not None:
        stmt = stmt.where(Listing.area_m2 <= area_max)
    if price_min is not None:
        stmt = stmt.where(Listing.price_usd >= price_min)
    if price_max is not None:
        stmt = stmt.where(Listing.price_usd <= price_max)
    if ppm_min is not None:
        stmt = stmt.where(Listing.price_per_m2_usd >= ppm_min)
    if ppm_max is not None:
        stmt = stmt.where(Listing.price_per_m2_usd <= ppm_max)
    if source:
        stmt = stmt.where(Listing.source == source)

    total = count_listings(db, stmt)
    if sort == "price_per_m2":
        stmt = stmt.order_by(asc(Listing.price_per_m2_usd))
    elif sort == "fresh":
        stmt = stmt.order_by(desc(Listing.seen_at))
    elif sort == "price":
        stmt = stmt.order_by(asc(Listing.price_usd))
    else:
        stmt = stmt.order_by(asc(Listing.price_per_m2_usd))

    listings = list(db.scalars(stmt.limit(limit).offset(offset)).all())
    items = [_with_market(db, listing) for listing in listings]
    if discount_min is not None:
        items = [item for item in items if item.market and item.market.discount_percent is not None and item.market.discount_percent >= discount_min]
        total = len(items)
    if sort == "discount":
        items.sort(key=lambda item: item.market.discount_percent if item.market and item.market.discount_percent is not None else -999, reverse=True)
    return ListingsPage(items=items, total=total)


@router.get("/listings/stats")
def get_listings_stats(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    base_filters = (
        Listing.status == "active",
        Listing.price_usd >= settings.min_listing_price_usd,
        Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
    )
    rows = db.execute(
        select(
            Listing.id,
            Listing.source,
            Listing.district,
            Listing.rooms,
            Listing.building_key,
            Listing.price_per_m2_usd,
            Listing.created_at,
        ).where(*base_filters)
    ).all()

    building_groups: dict[str, list[float]] = defaultdict(list)
    district_room_groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in rows:
        if row.price_per_m2_usd is None:
            continue
        if row.building_key:
            building_groups[row.building_key].append(row.price_per_m2_usd)
        district_room_groups[(row.district, row.rooms)].append(row.price_per_m2_usd)

    building_avg = {k: sum(v) / len(v) for k, v in building_groups.items() if len(v) >= 2}
    district_room_median = {k: float(median(v)) for k, v in district_room_groups.items() if len(v) >= 3}

    threshold = get_settings().below_market_threshold * 100
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    total = 0
    hot = 0
    new_today_hot = 0
    new_yesterday_hot = 0
    sources_total: dict[str, int] = defaultdict(int)
    sources_hot: dict[str, int] = defaultdict(int)

    for row in rows:
        total += 1
        sources_total[row.source] += 1
        if row.price_per_m2_usd is None or row.price_per_m2_usd <= 0:
            continue
        market = None
        if row.building_key:
            market = building_avg.get(row.building_key)
        if market is None:
            market = district_room_median.get((row.district, row.rooms))
        if not market or market <= 0:
            continue
        discount = (1 - row.price_per_m2_usd / market) * 100
        if discount >= threshold:
            hot += 1
            sources_hot[row.source] += 1
            if row.created_at and row.created_at >= today_start:
                new_today_hot += 1
            elif row.created_at and row.created_at >= yesterday_start:
                new_yesterday_hot += 1

    sources = []
    for source in sorted(sources_total.keys()):
        sources.append({
            "source": source,
            "total": sources_total[source],
            "hot": sources_hot.get(source, 0),
        })

    return {
        "total": total,
        "hot": hot,
        "new_today": new_today_hot,
        "new_yesterday": new_yesterday_hot,
        "sources": sources,
        "hot_threshold_percent": threshold,
    }


@router.get("/listings/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: int, db: Session = Depends(get_db)) -> ListingOut:
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return _with_market(db, listing)


@router.get("/market/estimate", response_model=MarketEstimate)
def get_market_estimate(
    district: str,
    rooms: int,
    area_m2: float,
    building_key: Optional[str] = None,
    listing_price_per_m2: Optional[float] = None,
    db: Session = Depends(get_db),
) -> MarketEstimate:
    estimate = estimate_market(
        db,
        district=district,
        rooms=rooms,
        area_m2=area_m2,
        building_key=building_key,
        listing_price_per_m2=listing_price_per_m2,
    )
    return MarketEstimate(**estimate.__dict__)


def _with_market(db: Session, listing: Listing) -> ListingOut:
    estimate = estimate_market(
        db,
        district=listing.district,
        rooms=listing.rooms,
        area_m2=listing.area_m2,
        building_key=listing.building_key,
        listing_price_per_m2=listing.price_per_m2_usd,
        exclude_listing_id=listing.id,
    )
    data = listing_to_dict(listing)
    data["market"] = MarketEstimate(**estimate.__dict__)
    return ListingOut(**data)
