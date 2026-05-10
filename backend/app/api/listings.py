from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

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
    stmt = select(Listing).where(Listing.status == "active")
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
