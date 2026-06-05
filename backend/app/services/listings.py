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
# Импорт здесь, а не наверху — market_estimate сам импортирует cma → models;
# держим как явный импорт чтобы не было сюрпризов при тестировании.
from app.services.market_estimate import compute_and_store as _compute_market_estimate


RELIST_GAP_DAYS = 3
# Источники (OLX/Uybor) показывают USD-эквивалент UZS-цены по своему живому курсу,
# поэтому при каждом скрейпе цена «дрожит» на десятые доли процента без реальных
# действий продавца. Пишем событие price_changed только на СНИЖЕНИЯ цены строго
# больше 1%: повышения почти всегда либо курсовой шум, либо переоценка хозяином
# (нам интереснее торг вниз, а не вверх).
PRICE_CHANGE_MIN_PCT = 0.01  # > 1%
DELIST_THRESHOLD_DAYS = 3


def _is_significant_price_change(prev: float | None, new: float | None) -> bool:
    if prev is None or new is None or prev <= 0:
        return False
    if new >= prev:
        return False
    return ((prev - new) / prev) > PRICE_CHANGE_MIN_PCT


def _should_preserve_olx_detail_price(listing: Listing, raw: RawListing) -> bool:
    """Keep a detail-page-confirmed OLX USD price through search-page refreshes.

    OLX search pages report every card as UZS. For ads whose detail page says
    the seller entered у.е., archive_sweep / the new-listing probe rewrite
    ``currency`` to USD. A search-page UZS card must NEVER overwrite that
    authoritative USD ask: ``to_usd`` divides by a fixed rate while the search
    card uses OLX's live rate, so the converted estimate runs ~5% low and would
    both corrupt the price and emit a bogus ``price_changed`` (FX drift alone
    can breach any fixed ratio window). A search refresh still updates
    metadata/seen_at, but the price stays frozen here. Genuine seller price
    changes are picked up by re-probing the detail page in the live scan
    (``scrape._reprobe_known_olx_listing``): by the time a real update reaches
    upsert the raw already carries ``currency='USD'``, so this guard is False
    and the normal update path runs.
    """
    if raw.source != "olx" or raw.currency.upper() != "UZS":
        return False
    if listing.source != "olx" or listing.currency.upper() != "USD":
        return False
    if not listing.price_usd or listing.price_usd <= 0:
        return False
    return True


def upsert_raw_listing(db: Session, raw: RawListing) -> tuple[Listing, bool]:
    db.flush()
    existing = db.scalar(select(Listing).where(Listing.source == raw.source, Listing.source_id == raw.source_id))
    price_usd = to_usd(raw.price, raw.currency)
    ppm = price_per_m2(price_usd, raw.area_m2)
    building_key = normalize_building_key(raw.district, raw.address_raw)
    group_key = duplicate_group_key(raw.district, raw.address_raw, raw.rooms, raw.area_m2, price_usd)

    duplicate = find_duplicate(db, group_key, raw.source, raw.source_id)
    if duplicate is None:
        duplicate = find_duplicate_by_flat(db, raw, price_usd)
    source_urls = [{"source": raw.source, "url": raw.url}]

    now = utcnow()
    events: list[dict] = []

    if existing:
        listing = existing
        is_new = False
        prev_price = existing.price_usd
        prev_status = existing.status
        prev_seen_at = existing.seen_at
        preserve_detail_price = _should_preserve_olx_detail_price(existing, raw)
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
        if not preserve_detail_price and _is_significant_price_change(prev_price, price_usd):
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
        preserve_detail_price = _should_preserve_olx_detail_price(duplicate, raw)
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
        if not preserve_detail_price and _is_significant_price_change(prev_price, price_usd):
            events.append({
                "event_type": "price_changed",
                "old_price_usd": prev_price,
                "new_price_usd": price_usd,
                "source": raw.source,
                "source_id": raw.source_id,
            })
    else:
        listing = Listing(source=raw.source, source_id=raw.source_id, url=raw.url, duplicate_group_key=group_key)
        db.add(listing)
        is_new = True
        preserve_detail_price = False
        events.append({
            "event_type": "first_seen",
            "new_price_usd": price_usd,
            "new_status": "active",
            "source": raw.source,
            "source_id": raw.source_id,
        })

    # When the incoming row is a same-flat repost (matched via find_duplicate),
    # only overwrite the canonical's displayed fields if it's a cheaper ask —
    # the "ниже рынка" panel surfaces the best deal per flat, so the canonical
    # should track the lowest price seen for it.
    is_duplicate_branch = existing is None and duplicate is not None
    incoming_is_cheaper = (
        price_usd is not None
        and (listing.price_usd is None or price_usd < listing.price_usd)
    )
    overwrite_canonical = not is_duplicate_branch or incoming_is_cheaper

    if overwrite_canonical:
        listing.source = raw.source
        listing.source_id = raw.source_id
        listing.url = raw.url
        listing.title = raw.title
        if not preserve_detail_price:
            listing.price = raw.price
            listing.currency = raw.currency
            listing.price_usd = price_usd
        listing.area_m2 = raw.area_m2
        if not preserve_detail_price:
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
        listing.deal_type = raw.deal_type
        listing.price_period = raw.price_period
        listing.published_at = raw.published_at
    # Floor is a physical property of the flat, identical across reposts — fill
    # it from any incoming row that knows it, even a not-cheaper duplicate that
    # the block above won't overwrite. Stops floor=None from sticking forever.
    if listing.floor is None and raw.floor is not None:
        listing.floor = raw.floor
    if listing.total_floors is None and raw.total_floors is not None:
        listing.total_floors = raw.total_floors
    listing.seen_at = now
    listing.status = "active"
    listing.source_urls = dumps_json(merge_source_urls(loads_json(listing.source_urls, []), source_urls))
    listing.duplicate_count = max(1, len(loads_json(listing.source_urls, [])))

    if events:
        db.flush()
        for payload in events:
            db.add(ListingEvent(listing_id=listing.id, at=now, **payload))

    # Считаем оценку рынка для этого листинга сразу: пеерс-выборка берётся
    # из текущего состояния БД (других листингов в этом же скрейп-проходе).
    # Полный пересчёт всей базы — в ночном batch'е, чтобы соседи перестроились
    # друг под друга.
    db.flush()
    _compute_market_estimate(db, listing)

    return listing, is_new


def find_duplicate(db: Session, group_key: str, source: str, source_id: str) -> Listing | None:
    return db.scalar(
        select(Listing).where(
            Listing.duplicate_group_key == group_key,
            or_(Listing.source != source, Listing.source_id != source_id),
        )
    )


# Width of the price window used to match the same flat reposted at a slightly
# different ask. 5% is wide enough to absorb FX-rate drift and small bargaining
# adjustments, tight enough that genuinely different flats don't merge.
LOOSE_DEDUP_PRICE_TOLERANCE = 0.05


def find_duplicate_by_flat(db: Session, raw: RawListing, price_usd: float) -> Listing | None:
    """Same-source second-pass match for reposts that the hashed fingerprint
    misses because title/address text drifted.

    Floor is treated as wildcard-compatible: a missing floor on the incoming
    raw matches any existing row, and vice versa. ``total_floors`` is no
    longer part of the match — district + rooms + area + price-within-±5%
    is already a strong same-flat signal, and OLX cards routinely omit the
    building height field.
    """
    if not price_usd or raw.area_m2 is None or raw.rooms is None:
        return None
    price_lo = price_usd * (1 - LOOSE_DEDUP_PRICE_TOLERANCE)
    price_hi = price_usd * (1 + LOOSE_DEDUP_PRICE_TOLERANCE)
    floor_clause = (
        or_(Listing.floor == raw.floor, Listing.floor.is_(None))
        if raw.floor is not None
        else True
    )
    return db.scalar(
        select(Listing).where(
            Listing.source == raw.source,
            Listing.district == raw.district,
            Listing.rooms == raw.rooms,
            Listing.area_m2 == raw.area_m2,
            floor_clause,
            Listing.price_usd.between(price_lo, price_hi),
            or_(Listing.source != raw.source, Listing.source_id != raw.source_id),
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


def mark_delisted_for_source(
    db: Session,
    source: str,
    threshold_days: int = DELIST_THRESHOLD_DAYS,
    deal_type: str | None = None,
) -> int:
    now = utcnow()
    cutoff = now - timedelta(days=threshold_days)
    # deal_type заскоуплен: sale-скан не должен снимать rent-листинги той же
    # площадки (source у них общий — 'uybor'/'olx'), и наоборот.
    conditions = [
        Listing.source == source,
        Listing.status == "active",
        Listing.seen_at < cutoff,
    ]
    if deal_type is not None:
        conditions.append(Listing.deal_type == deal_type)
    stale = db.scalars(select(Listing).where(*conditions)).all()
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
