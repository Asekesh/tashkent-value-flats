from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Listing, ListingEvent
from app.scrapers.base import RawListing
from app.services.normalization import (
    duplicate_group_key,
    dumps_json,
    loads_json,
    normalize_building_key,
    price_per_m2,
    to_usd,
    utcnow,
)


RELIST_GAP_DAYS = 3
PRICE_CHANGE_EPS_USD = 1.0
DELIST_THRESHOLD_DAYS = 3


def upsert_raw_listing(db: Session, raw: RawListing) -> tuple[Listing, bool]:
    db.flush()
    existing = db.scalar(select(Listing).where(Listing.source == raw.source, Listing.source_id == raw.source_id))
    price_usd = to_usd(raw.price, raw.currency)
    ppm = price_per_m2(price_usd, raw.area_m2)
    building_key = normalize_building_key(raw.district, raw.address_raw)
    group_key = duplicate_group_key(raw.district, raw.address_raw, raw.rooms, raw.area_m2, price_usd)

    duplicate = find_duplicate(db, group_key, raw.source, raw.source_id)
    source_urls = [{"source": raw.source, "url": raw.url}]

    now = utcnow()
    events: list[dict] = []

    if existing:
        listing = existing
        is_new = False
        prev_price = existing.price_usd
        prev_status = existing.status
        prev_seen_at = existing.seen_at
        if prev_status == "removed":
            events.append({
                "event_type": "relisted",
                "old_status": prev_status,
                "new_status": "active",
                "source": raw.source,
                "source_id": raw.source_id,
                "note": "Снова появилось после снятия",
            })
        elif prev_seen_at and (now - prev_seen_at) >= timedelta(days=RELIST_GAP_DAYS):
            gap_days = int((now - prev_seen_at).total_seconds() // 86400)
            events.append({
                "event_type": "relisted",
                "old_status": prev_status,
                "new_status": "active",
                "source": raw.source,
                "source_id": raw.source_id,
                "note": f"Пропадало {gap_days} дн.",
            })
        if prev_price is not None and abs((price_usd or 0) - prev_price) >= PRICE_CHANGE_EPS_USD:
            events.append({
                "event_type": "price_changed",
                "old_price_usd": prev_price,
                "new_price_usd": price_usd,
                "source": raw.source,
                "source_id": raw.source_id,
            })
    elif duplicate:
        listing = duplicate
        is_new = False
        prev_price = duplicate.price_usd
        prev_status = duplicate.status
        prev_seen_at = duplicate.seen_at
        is_new_source = (duplicate.source, duplicate.source_id) != (raw.source, raw.source_id)
        gap_old = prev_seen_at and (now - prev_seen_at) >= timedelta(days=RELIST_GAP_DAYS)
        if is_new_source and (prev_status == "removed" or gap_old):
            note = "Перевыставлено как новое объявление"
            if gap_old and prev_seen_at:
                note += f" (последний раз видели {int((now - prev_seen_at).total_seconds() // 86400)} дн. назад)"
            events.append({
                "event_type": "relisted",
                "old_status": prev_status,
                "new_status": "active",
                "source": raw.source,
                "source_id": raw.source_id,
                "note": note,
            })
        if prev_price is not None and abs((price_usd or 0) - prev_price) >= PRICE_CHANGE_EPS_USD:
            events.append({
                "event_type": "price_changed",
                "old_price_usd": prev_price,
                "new_price_usd": price_usd,
                "source": raw.source,
                "source_id": raw.source_id,
            })
        source_urls = merge_source_urls(loads_json(listing.source_urls, []), source_urls)
        listing.duplicate_count = len(source_urls)
    else:
        listing = Listing(source=raw.source, source_id=raw.source_id, url=raw.url, duplicate_group_key=group_key)
        db.add(listing)
        is_new = True
        events.append({
            "event_type": "first_seen",
            "new_price_usd": price_usd,
            "new_status": "active",
            "source": raw.source,
            "source_id": raw.source_id,
        })

    listing.title = raw.title
    listing.price = raw.price
    listing.currency = raw.currency
    listing.price_usd = price_usd
    listing.area_m2 = raw.area_m2
    listing.price_per_m2_usd = ppm
    listing.rooms = raw.rooms
    listing.floor = raw.floor
    listing.total_floors = raw.total_floors
    listing.district = raw.district
    listing.address_raw = raw.address_raw
    listing.building_key = building_key
    listing.description = raw.description
    listing.photos = dumps_json(raw.photos)
    listing.seller_type = raw.seller_type
    listing.published_at = raw.published_at
    listing.seen_at = now
    listing.status = "active"
    listing.source_urls = dumps_json(merge_source_urls(loads_json(listing.source_urls, []), source_urls))
    listing.duplicate_count = max(1, len(loads_json(listing.source_urls, [])))

    if events:
        db.flush()
        for payload in events:
            db.add(ListingEvent(listing_id=listing.id, at=now, **payload))

    return listing, is_new


def find_duplicate(db: Session, group_key: str, source: str, source_id: str) -> Listing | None:
    return db.scalar(
        select(Listing).where(
            Listing.duplicate_group_key == group_key,
            or_(Listing.source != source, Listing.source_id != source_id),
        )
    )


def merge_source_urls(existing: list[dict], incoming: list[dict]) -> list[dict]:
    seen = {(item.get("source"), item.get("url")) for item in existing}
    merged = list(existing)
    for item in incoming:
        key = (item.get("source"), item.get("url"))
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def listing_to_dict(listing: Listing) -> dict:
    return {
        "id": listing.id,
        "source": listing.source,
        "source_id": listing.source_id,
        "url": listing.url,
        "title": listing.title,
        "price": listing.price,
        "currency": listing.currency,
        "price_usd": listing.price_usd,
        "area_m2": listing.area_m2,
        "price_per_m2_usd": listing.price_per_m2_usd,
        "rooms": listing.rooms,
        "floor": listing.floor,
        "total_floors": listing.total_floors,
        "district": listing.district,
        "address_raw": listing.address_raw,
        "building_key": listing.building_key,
        "description": listing.description,
        "photos": loads_json(listing.photos, []),
        "seller_type": listing.seller_type,
        "published_at": listing.published_at,
        "seen_at": listing.seen_at,
        "status": listing.status,
        "duplicate_count": listing.duplicate_count,
        "source_urls": loads_json(listing.source_urls, []),
    }


def count_listings(db: Session, stmt) -> int:
    count_stmt = select(func.count()).select_from(stmt.subquery())
    return int(db.scalar(count_stmt) or 0)


def mark_delisted_for_source(db: Session, source: str, threshold_days: int = DELIST_THRESHOLD_DAYS) -> int:
    now = utcnow()
    cutoff = now - timedelta(days=threshold_days)
    stale = db.scalars(
        select(Listing).where(
            Listing.source == source,
            Listing.status == "active",
            Listing.seen_at < cutoff,
        )
    ).all()
    for listing in stale:
        prev_price = listing.price_usd
        listing.status = "removed"
        db.add(
            ListingEvent(
                listing_id=listing.id,
                event_type="delisted",
                old_status="active",
                new_status="removed",
                old_price_usd=prev_price,
                source=source,
                source_id=listing.source_id,
                note=f"Не видели {threshold_days}+ дн.",
                at=now,
            )
        )
    return len(stale)
