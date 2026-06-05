from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, func, nulls_last, select
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
    floor_min: Optional[int] = None,
    floor_max: Optional[int] = None,
    discount_min: Optional[float] = None,
    source: Optional[str] = None,
    deal_type: Literal["sale", "rent"] = "sale",
    sort: Literal["discount", "price_per_m2", "fresh", "price"] = "discount",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ListingsPage:
    settings = get_settings()
    # Фильтры собираем в список условий, чтобы переиспользовать их и для
    # подсчёта total, и для самой страницы.
    conditions = [
        Listing.status == "active",
        Listing.deal_type == deal_type,  # вкладка: продажа/аренда, дефолт sale (старый фронт)
        Listing.price_usd >= settings.min_listing_price_usd,
        Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
    ]
    if district:
        districts = [d.strip() for d in district.split(",") if d.strip()]
        if len(districts) == 1:
            conditions.append(Listing.district == districts[0])
        elif districts:
            conditions.append(Listing.district.in_(districts))
    if rooms:
        conditions.append(Listing.rooms == rooms)
    if area_min is not None:
        conditions.append(Listing.area_m2 >= area_min)
    if area_max is not None:
        conditions.append(Listing.area_m2 <= area_max)
    if price_min is not None:
        conditions.append(Listing.price_usd >= price_min)
    if price_max is not None:
        conditions.append(Listing.price_usd <= price_max)
    if ppm_min is not None:
        conditions.append(Listing.price_per_m2_usd >= ppm_min)
    if ppm_max is not None:
        conditions.append(Listing.price_per_m2_usd <= ppm_max)
    if floor_min is not None:
        conditions.append(Listing.floor >= floor_min)
    if floor_max is not None:
        conditions.append(Listing.floor <= floor_max)
    if source:
        conditions.append(Listing.source == source)
    if discount_min is not None:
        # discount_percent заполняется только вместе с market-оценкой
        # (apply_estimate всегда пишет market_basis), поэтому отбор по самой
        # колонке эквивалентен прежнему "item.market and discount >= min";
        # SQL `>=` уже отсекает NULL.
        conditions.append(Listing.discount_percent >= discount_min)

    # Сортировка и пагинация — на стороне БД (раньше тянули ВСЕ подходящие
    # строки в Python и резали там). discount_percent/price*/seen_at —
    # индексированы. discount_percent NULL ⇒ market нет ⇒ NULLS LAST совпадает
    # со старым сентинелом -999.
    if sort == "price_per_m2":
        order_by = [nulls_last(asc(Listing.price_per_m2_usd)), Listing.id.asc()]
    elif sort == "fresh":
        order_by = [nulls_last(Listing.seen_at.desc()), Listing.id.desc()]
    elif sort == "price":
        order_by = [nulls_last(asc(Listing.price_usd)), Listing.id.asc()]
    else:  # discount (по умолчанию)
        order_by = [nulls_last(Listing.discount_percent.desc()), Listing.id.asc()]

    total = db.scalar(select(func.count()).select_from(Listing).where(*conditions)) or 0
    rows = db.scalars(
        select(Listing).where(*conditions).order_by(*order_by).limit(limit).offset(offset)
    ).all()
    items = [_build_item(listing) for listing in rows]
    return ListingsPage(items=items, total=total)


@router.get("/listings/stats")
def get_listings_stats(
    db: Session = Depends(get_db),
    deal_type: Literal["sale", "rent"] = "sale",
) -> dict:
    settings = get_settings()
    rows = db.execute(
        select(
            Listing.source,
            Listing.district,
            Listing.created_at,
            Listing.discount_percent,
        ).where(
            Listing.status == "active",
            Listing.deal_type == deal_type,
            Listing.price_usd >= settings.min_listing_price_usd,
            Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
        )
    ).all()

    threshold = settings.below_market_threshold * 100
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    total = 0
    hot = 0
    new_today_hot = 0
    new_yesterday_hot = 0
    sources_total: dict[str, int] = defaultdict(int)
    sources_hot: dict[str, int] = defaultdict(int)
    districts_set: set[str] = set()

    for row in rows:
        total += 1
        sources_total[row.source] += 1
        if row.district:
            districts_set.add(row.district)
        if row.discount_percent is None or row.discount_percent < threshold:
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
        "districts": sorted(districts_set),
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
    segment: Optional[Literal["new", "secondary"]] = None,
    floor: Optional[int] = None,
    total_floors: Optional[int] = None,
    db: Session = Depends(get_db),
) -> MarketEstimate:
    estimate = estimate_market(
        db,
        district=district,
        rooms=rooms,
        area_m2=area_m2,
        building_key=building_key,
        listing_price_per_m2=listing_price_per_m2,
        segment=segment,
        floor=floor,
        total_floors=total_floors,
    )
    return MarketEstimate(**estimate.__dict__)


def _build_item(listing: Listing) -> ListingOut:
    data = listing_to_dict(listing)
    if listing.market_basis or listing.market_price_per_m2_usd is not None:
        data["market"] = MarketEstimate(
            market_price_per_m2_usd=listing.market_price_per_m2_usd,
            sample_size=listing.market_sample_size or 0,
            basis=listing.market_basis or "insufficient_data",
            confidence=listing.market_confidence or "low",
            discount_percent=listing.discount_percent,
            is_below_market=bool(listing.is_below_market),
        )
    else:
        data["market"] = None
    return ListingOut(**data)


def _with_market(db: Session, listing: Listing) -> ListingOut:
    return _build_item(listing)
