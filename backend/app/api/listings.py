from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import Listing, ListingEvent
from app.schemas.listing import (
    CmaResultOut,
    ListingEventOut,
    ListingHistoryOut,
    ListingHistorySummary,
    ListingOut,
    ListingsPage,
    MarketEstimate,
)
from app.services.cma import build_cma
from app.services.listings import listing_to_dict
from app.services.market import (
    MarketIndex,
    build_market_index,
    estimate_from_index,
    estimate_market,
)

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

    # Один индекс рынка на весь запрос — та же формула, что в /listings/stats.
    index = build_market_index(db)
    all_listings = list(db.scalars(stmt).all())
    items = [_build_item(listing, index) for listing in all_listings]

    if discount_min is not None:
        items = [
            item for item in items
            if item.market and item.market.discount_percent is not None
            and item.market.discount_percent >= discount_min
        ]

    if sort == "discount":
        items.sort(key=lambda item: item.market.discount_percent if item.market and item.market.discount_percent is not None else -999, reverse=True)
    elif sort == "price_per_m2":
        items.sort(key=lambda item: item.price_per_m2_usd if item.price_per_m2_usd is not None else 1e18)
    elif sort == "fresh":
        items.sort(key=lambda item: item.seen_at or "", reverse=True)
    elif sort == "price":
        items.sort(key=lambda item: item.price_usd if item.price_usd is not None else 1e18)

    total = len(items)
    page = items[offset : offset + limit]
    return ListingsPage(items=page, total=total)


@router.get("/listings/stats")
def get_listings_stats(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    rows = db.execute(
        select(
            Listing.source,
            Listing.district,
            Listing.rooms,
            Listing.building_key,
            Listing.price_per_m2_usd,
            Listing.area_m2,
            Listing.created_at,
        ).where(
            Listing.status == "active",
            Listing.price_usd >= settings.min_listing_price_usd,
            Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
        )
    ).all()

    index = build_market_index(db)
    threshold = settings.below_market_threshold * 100
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
        estimate = estimate_from_index(
            index,
            building_key=row.building_key,
            district=row.district,
            rooms=row.rooms,
            area_m2=row.area_m2,
            listing_price_per_m2=row.price_per_m2_usd,
        )
        if estimate.discount_percent is None or estimate.discount_percent < threshold:
            continue
        hot += 1
        sources_hot[row.source] += 1
        if row.created_at and row.created_at >= today_start:
            new_today_hot += 1
        elif row.created_at and row.created_at >= yesterday_start:
            new_yesterday_hot += 1

    sources = [
        {
            "source": source,
            "total": sources_total[source],
            "hot": sources_hot.get(source, 0),
        }
        for source in sorted(sources_total.keys())
    ]

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


@router.get("/listings/{listing_id}/history", response_model=ListingHistoryOut)
def get_listing_history(listing_id: int, db: Session = Depends(get_db)) -> ListingHistoryOut:
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    events = list(
        db.scalars(
            select(ListingEvent).where(ListingEvent.listing_id == listing_id).order_by(asc(ListingEvent.at))
        ).all()
    )

    first_seen = next((e for e in events if e.event_type == "first_seen"), None)
    relists = [e for e in events if e.event_type == "relisted"]
    delists = [e for e in events if e.event_type == "delisted"]
    price_events = [e for e in events if e.event_type == "price_changed"]

    first_price = first_seen.new_price_usd if first_seen else None
    current_price = listing.price_usd
    change_percent: Optional[float] = None
    if first_price and first_price > 0 and current_price is not None:
        change_percent = (current_price - first_price) / first_price * 100

    summary = ListingHistorySummary(
        first_seen_at=first_seen.at if first_seen else listing.created_at,
        first_price_usd=first_price,
        current_price_usd=current_price,
        total_price_change_percent=change_percent,
        price_change_count=len(price_events),
        relisted_count=len(relists),
        last_relisted_at=relists[-1].at if relists else None,
        last_delisted_at=delists[-1].at if delists else None,
    )

    return ListingHistoryOut(
        listing_id=listing_id,
        summary=summary,
        events=[ListingEventOut.model_validate(e) for e in reversed(events)],
    )


@router.get("/cma/{listing_id}", response_model=CmaResultOut)
def get_cma(listing_id: int, db: Session = Depends(get_db)) -> CmaResultOut:
    listing = db.get(Listing, listing_id)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    result = build_cma(db, listing)
    return CmaResultOut(
        subject=result.subject.__dict__,
        basis=result.basis,
        basis_label=result.basis_label,
        area_tolerance_percent=result.area_tolerance_percent,
        stats=result.stats.__dict__,
        subject_vs_market_percent=result.subject_vs_market_percent,
        analogs=[a.__dict__ for a in result.analogs],
    )


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


def _build_item(listing: Listing, index: MarketIndex) -> ListingOut:
    estimate = estimate_from_index(
        index,
        building_key=listing.building_key,
        district=listing.district,
        rooms=listing.rooms,
        area_m2=listing.area_m2,
        listing_price_per_m2=listing.price_per_m2_usd,
    )
    data = listing_to_dict(listing)
    data["market"] = MarketEstimate(**estimate.__dict__)
    return ListingOut(**data)


def _with_market(db: Session, listing: Listing) -> ListingOut:
    return _build_item(listing, build_market_index(db))
