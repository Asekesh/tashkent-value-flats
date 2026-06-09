from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Listing, ListingEvent, ResidentialComplex
from app.scrapers.base import RawListing
from app.services.normalization import (
    clean_complex_name,
    complex_match_key,
    duplicate_group_key,
    dumps_json,
    extract_complex_name,
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


def _coords_rank(precision: str | None) -> int:
    """Ранг точности координат: exact (Uybor) > approx (OLX) > нет.
    Используется в upsert, чтобы approx не затирал exact, а NULL — известную точку."""
    return {"exact": 2, "approx": 1}.get(precision or "", 0)


def upsert_raw_listing(db: Session, raw: RawListing) -> tuple[Listing, bool]:
    db.flush()
    existing = db.scalar(select(Listing).where(Listing.source == raw.source, Listing.source_id == raw.source_id))
    price_usd = to_usd(raw.price, raw.currency)
    ppm = price_per_m2(price_usd, raw.area_m2)
    building_key = normalize_building_key(raw.district, raw.address_raw)
    group_key = duplicate_group_key(raw.district, raw.address_raw, raw.rooms, raw.area_m2, price_usd)

    duplicate = find_duplicate(db, group_key, raw.source, raw.source_id, raw.deal_type)
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
        # seller_type у части источников (uybor) проставляет классификатор по объёму
        # (см. classify_sellers_by_volume) — не затираем его None'ом из адаптера.
        if raw.seller_type is not None:
            listing.seller_type = raw.seller_type
        listing.seller_id = raw.seller_id
        # is_business даёт только OLX из embedded-state; reprobe/детальный проход
        # его не несут — не затираем уже известный флаг None'ом.
        if raw.is_business is not None:
            listing.is_business = raw.is_business
        listing.deal_type = raw.deal_type
        listing.price_period = raw.price_period
        # Поля аренды: только OLX (структурно) и Uybor (из текста) их несут;
        # reprobe/детальный проход — нет, поэтому не затираем известное None'ом.
        if raw.is_furnished is not None:
            listing.is_furnished = raw.is_furnished
        if raw.commission_pct is not None:
            listing.commission_pct = raw.commission_pct
        listing.published_at = raw.published_at
    # Floor is a physical property of the flat, identical across reposts — fill
    # it from any incoming row that knows it, even a not-cheaper duplicate that
    # the block above won't overwrite. Stops floor=None from sticking forever.
    if listing.floor is None and raw.floor is not None:
        listing.floor = raw.floor
    if listing.total_floors is None and raw.total_floors is not None:
        listing.total_floors = raw.total_floors
    # Координаты для карты (миграция 0018). Источник-агностично, как floor: льём
    # из любой строки, что их знает (даже не-дешевле дубля). Но точность ранжируем —
    # exact (Uybor) бьёт approx (OLX), approx НЕ затирает exact, NULL НЕ затирает
    # известную точку. Координаты НЕ участвуют в building_key/group_key/дедупе.
    if raw.lat is not None and raw.lng is not None:
        existing_rank = _coords_rank(listing.coords_precision) if listing.lat is not None else -1
        if _coords_rank(raw.coords_precision) >= existing_rank:
            listing.lat = raw.lat
            listing.lng = raw.lng
            listing.coords_precision = raw.coords_precision
    # ЖК (Шаг 3e): имя сидит в тексте, тянем источник-агностично из адреса+описания.
    # Не затираем уже проставленный id None'ом из не-дешевле дубля без названия.
    complex_name = extract_complex_name(f"{raw.address_raw or ''} {raw.description or ''}")
    if complex_name:
        rc_id = resolve_residential_complex(db, complex_name, listing.district)
        if rc_id and (overwrite_canonical or listing.residential_complex_id is None):
            listing.residential_complex_id = rc_id
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


def find_duplicate(db: Session, group_key: str, source: str, source_id: str, deal_type: str = "sale") -> Listing | None:
    # deal_type-скоуп обязателен: source у аренды и продажи общий ('uybor'/'olx'),
    # а price_bucket в group_key может совпасть (дешёвая продажа vs дорогая аренда).
    # Без него rent-строка матчилась бы как дубль sale и перезаписывала её.
    return db.scalar(
        select(Listing).where(
            Listing.duplicate_group_key == group_key,
            Listing.deal_type == deal_type,
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
            Listing.deal_type == raw.deal_type,  # не схлопывать аренду с продажей (source общий)
            Listing.district == raw.district,
            Listing.rooms == raw.rooms,
            Listing.area_m2 == raw.area_m2,
            floor_clause,
            Listing.price_usd.between(price_lo, price_hi),
            or_(Listing.source != raw.source, Listing.source_id != raw.source_id),
        )
    )


def resolve_residential_complex(
    db: Session, name: str, district: str | None, cache: dict[str, int] | None = None
) -> int | None:
    """Апсерт ЖК по match_key: разные написания одного ЖК схлопываются в одну
    строку справочника. Возвращает id или None, если имя «пустое». ``cache``
    (match_key→id) избавляет бэкфилл от per-row SELECT по сети."""
    key = complex_match_key(name)
    if len(key) < 2:
        return None
    if cache is not None and key in cache:
        return cache[key]
    existing = db.scalar(select(ResidentialComplex).where(ResidentialComplex.match_key == key))
    if existing:
        if cache is not None:
            cache[key] = existing.id
        return existing.id
    complex_row = ResidentialComplex(name=name, match_key=key, district=district)
    try:
        # savepoint: гонка на unique(match_key) (живой скрейпер пишет параллельно)
        # не должна валить весь upsert/бэкфилл.
        with db.begin_nested():
            db.add(complex_row)
        rc_id = complex_row.id
    except IntegrityError:
        rc_id = db.scalar(select(ResidentialComplex.id).where(ResidentialComplex.match_key == key))
    if cache is not None and rc_id is not None:
        cache[key] = rc_id
    return rc_id


def backfill_residential_complexes(
    db: Session, dry_run: bool = False, limit: int | None = None, after_id: int = 0
) -> dict:
    """Разовый проход по листингам без residential_complex_id — тянет ЖК из
    текста и проставляет FK. Новые скрейпы заполняют поле сами в upsert.

    Эффективность: справочник ЖК предзагружается в память один раз, в цикле нет
    per-row SELECT — иначе 31k строк не укладываются в таймаут шлюза.

    Пагинация КУРСОРОМ по ``after_id`` (не offset): строки без ЖК остаются с
    NULL-FK, поэтому limit+order_by всегда возвращал бы ту же «голову» и
    зацикливался. Клиент идёт чанками: after_id = ответный ``next_after_id``,
    пока ``scanned`` > 0."""
    stmt = (
        select(Listing)
        .where(Listing.residential_complex_id.is_(None), Listing.id > after_id)
        .order_by(Listing.id)
    )
    if limit:
        stmt = stmt.limit(limit)
    rows = list(db.scalars(stmt).all())
    cache: dict[str, int] = {
        rc.match_key: rc.id for rc in db.scalars(select(ResidentialComplex)).all()
    }
    pending_keys: set[str] = set()  # для dry_run: новые ЖК, которые создались бы
    updated = 0
    for listing in rows:
        name = extract_complex_name(f"{listing.address_raw or ''} {listing.description or ''}")
        if not name:
            continue
        key = complex_match_key(name)
        if len(key) < 2:
            continue
        if dry_run:
            if key not in cache:
                pending_keys.add(key)
            updated += 1
            continue
        rc_id = resolve_residential_complex(db, name, listing.district, cache=cache)
        if rc_id is None:
            continue
        listing.residential_complex_id = rc_id
        updated += 1
    if not dry_run:
        db.commit()
    return {
        "scanned": len(rows),
        "updated": updated,
        "dry_run": dry_run,
        "next_after_id": rows[-1].id if rows else after_id,
    }


def remerge_residential_complexes(db: Session, dry_run: bool = False) -> dict:
    """Пересобирает справочник ЖК под ОБНОВЛЁННЫЙ complex_match_key: разные
    написания одного ЖК («Nest One»/«Nest One вид»/«Акай Сити»/«Akay City»)
    схлопывает в одну строку. Для каждого нового ключа канон = строка с
    наибольшим числом активных листингов; листинги остальных строк группы
    переносятся на канон, дубли удаляются, канону проставляется новый ключ и
    чистое имя. Сироты (имя выродилось в чистый шум → ключ < 2) — отвязываем и
    удаляем, иначе агрегат «по ЖК» получил бы мусорный ЖК. Идемпотентна.

    Запускать ОДИН раз после деплоя нового нормализатора (новые скрейпы уже
    кладутся правильным ключом). Строк в справочнике немного (~3k) → один
    проход/транзакция, без курсора."""
    counts: dict[int, int] = dict(
        db.execute(
            select(Listing.residential_complex_id, func.count())
            .where(Listing.residential_complex_id.is_not(None), Listing.status == "active")
            .group_by(Listing.residential_complex_id)
        ).all()
    )
    rows = list(db.scalars(select(ResidentialComplex)).all())
    groups: dict[str, list[ResidentialComplex]] = defaultdict(list)
    orphans: list[ResidentialComplex] = []
    for rc in rows:
        key = complex_match_key(rc.name)
        if len(key) < 2:
            orphans.append(rc)
        else:
            groups[key].append(rc)

    plan = []  # (canonical, others, new_key, new_name)
    for key, grp in groups.items():
        canonical = max(grp, key=lambda rc: (counts.get(rc.id, 0), -rc.id))
        others = [rc for rc in grp if rc.id != canonical.id]
        new_name = clean_complex_name(canonical.name) or canonical.name
        plan.append((canonical, others, key, new_name))

    merge_groups = sum(1 for _, others, _, _ in plan if others)
    rows_deleted = sum(len(others) for _, others, _, _ in plan)
    listings_repointed = sum(counts.get(rc.id, 0) for _, others, _, _ in plan for rc in others)
    rows_rekeyed = sum(
        1 for c, _, k, n in plan if c.match_key != k or c.name != n
    )

    if dry_run:
        return {
            "dry_run": True,
            "complexes_before": len(rows),
            "merge_groups": merge_groups,
            "rows_deleted": rows_deleted,
            "listings_repointed": listings_repointed,
            "rows_rekeyed": rows_rekeyed,
            "orphans_dropped": len(orphans),
            "complexes_after": len(rows) - rows_deleted - len(orphans),
        }

    # Пас 1: перенос листингов + удаление дублей и сирот. Делаем ДО смены ключей
    # канонов (пас 2), чтобы исключить даже теоретический транзиентный конфликт
    # на unique(match_key). rowcount считаем фактический (включая removed-листинги,
    # которые тоже должны переехать на канон) — отчёт точный, не оценка по active.
    repointed_actual = 0
    for canonical, others, _, _ in plan:
        if not others:
            continue
        other_ids = [rc.id for rc in others]
        res = db.execute(
            update(Listing)
            .where(Listing.residential_complex_id.in_(other_ids))
            .values(residential_complex_id=canonical.id)
        )
        repointed_actual += res.rowcount or 0
        db.flush()
        for rc in others:
            db.delete(rc)
        db.flush()
    orphan_listings_nulled = 0
    for rc in orphans:
        res = db.execute(
            update(Listing).where(Listing.residential_complex_id == rc.id).values(residential_complex_id=None)
        )
        orphan_listings_nulled += res.rowcount or 0
        db.delete(rc)
    db.flush()
    listings_repointed = repointed_actual  # перекрываем active-оценку фактическим rowcount

    # Пас 2: канону — новый ключ и чистое имя. Все дубли уже удалены → коллизий нет.
    for canonical, _, key, new_name in plan:
        if canonical.match_key != key:
            canonical.match_key = key
        if canonical.name != new_name:
            canonical.name = new_name
    db.commit()

    return {
        "dry_run": False,
        "complexes_before": len(rows),
        "merge_groups": merge_groups,
        "rows_deleted": rows_deleted,
        "listings_repointed": listings_repointed,
        "rows_rekeyed": rows_rekeyed,
        "orphans_dropped": len(orphans),
        "orphan_listings_nulled": orphan_listings_nulled,
        "complexes_after": len(rows) - rows_deleted - len(orphans),
    }


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
        "residential_complex_id": listing.residential_complex_id,
        "residential_complex": listing.residential_complex.name if listing.residential_complex else None,
        # Поля аренды (Numeric → float, чтобы pydantic не тащил Decimal).
        # deposit/utilities_included не отдаём: источники их не несут.
        "price_period": listing.price_period,
        "is_furnished": listing.is_furnished,
        "commission_pct": float(listing.commission_pct) if listing.commission_pct is not None else None,
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
