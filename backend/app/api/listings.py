from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, asc, func, nulls_last, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.session import get_db
from app.models import Listing, ListingEvent, ResidentialComplex
from app.schemas.listing import (
    CmaResultOut,
    ComplexComparison,
    ComplexStatOut,
    ComplexStatsPage,
    ListingEventOut,
    ListingHistoryOut,
    ListingHistorySummary,
    ListingOut,
    ListingsPage,
    MarketEstimate,
)
from app.services.cma import build_cma
from app.services.complex_stats import build_comparison, complex_comparison_map, list_complex_stats
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
    q: Optional[str] = None,  # «содержит»: слова в заголовке/описании/адресе, нужны ВСЕ
    exclude: Optional[str] = None,  # «исключить»: выкинуть, если есть ЛЮБОЕ слово
    source: Optional[str] = None,
    residential_complex: Optional[str] = None,  # поиск по имени ЖК (ILIKE)
    deal_type: Literal["sale", "rent"] = "sale",
    seller_type: Optional[Literal["owner", "agent", "unknown"]] = None,  # «без агентов» = owner
    sort: Literal["discount", "price_per_m2", "fresh", "price"] = "discount",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ListingsPage:
    settings = get_settings()
    # Фильтры собираем в список условий, чтобы переиспользовать их и для
    # подсчёта total, и для самой страницы.
    min_price_usd, min_ppm = settings.price_floors(deal_type)
    conditions = [
        Listing.status == "active",
        Listing.deal_type == deal_type,  # вкладка: продажа/аренда, дефолт sale (старый фронт)
        Listing.price_usd >= min_price_usd,
        Listing.price_per_m2_usd >= min_ppm,
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
    if residential_complex and residential_complex.strip():
        # Подзапрос вместо JOIN — встаёт в общий список conditions и работает
        # одинаково для count(total) и для самой страницы.
        like = f"%{residential_complex.strip()}%"
        conditions.append(
            Listing.residential_complex_id.in_(
                select(ResidentialComplex.id).where(ResidentialComplex.name.ilike(like))
            )
        )
    if seller_type:
        conditions.append(Listing.seller_type == seller_type)
    if discount_min is not None:
        # discount_percent заполняется только вместе с market-оценкой
        # (apply_estimate всегда пишет market_basis), поэтому отбор по самой
        # колонке эквивалентен прежнему "item.market and discount >= min";
        # SQL `>=` уже отсекает NULL.
        conditions.append(Listing.discount_percent >= discount_min)
    if q:
        # «содержит»: слова разделяем пробелом/запятой; каждое слово должно
        # встретиться в заголовке, описании ИЛИ адресе; нужны ВСЕ слова (И).
        for word in q.replace(",", " ").split():
            like = f"%{word}%"
            conditions.append(
                or_(
                    Listing.title.ilike(like),
                    Listing.description.ilike(like),
                    Listing.address_raw.ilike(like),
                )
            )
    if exclude:
        # «исключить»: выкидываем, если ЛЮБОЕ слово есть в заголовке/описании/адресе.
        # description nullable → NULL трактуем как «слова нет».
        for word in exclude.replace(",", " ").split():
            like = f"%{word}%"
            conditions.append(
                and_(
                    ~Listing.title.ilike(like),
                    ~Listing.address_raw.ilike(like),
                    or_(Listing.description.is_(None), ~Listing.description.ilike(like)),
                )
            )

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
        select(Listing)
        .where(*conditions)
        .options(selectinload(Listing.residential_complex))  # имя ЖК для карточки без N+1
        .order_by(*order_by)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [_build_item(listing) for listing in rows]
    _attach_complex_comparison(db, settings, rows, items, deal_type)
    return ListingsPage(items=items, total=total)


def _attach_complex_comparison(db, settings, rows, items, deal_type) -> None:
    """Вешает на каждый листинг сравнение с медианой его ЖК. Батч — один проход
    по всем ЖК страницы (без N+1). ЖК с <порога листингов пропускаем."""
    rc_ids = [r.residential_complex_id for r in rows if r.residential_complex_id is not None]
    comparison = complex_comparison_map(db, settings, rc_ids=rc_ids, deal_type=deal_type)
    if not comparison:
        return
    threshold = settings.below_market_threshold * 100
    for row, item in zip(rows, items):
        entry = comparison.get(row.residential_complex_id)
        if not entry:
            continue
        name, count, median_ppm = entry
        cmp = build_comparison(
            row.price_per_m2_usd, name, count, median_ppm, below_threshold_percent=threshold
        )
        item.complex_market = ComplexComparison(**cmp.__dict__)


@router.get("/listings/stats")
def get_listings_stats(
    db: Session = Depends(get_db),
    deal_type: Literal["sale", "rent"] = "sale",
) -> dict:
    settings = get_settings()
    min_price_usd, min_ppm = settings.price_floors(deal_type)
    rows = db.execute(
        select(
            Listing.source,
            Listing.district,
            Listing.created_at,
            Listing.discount_percent,
        ).where(
            Listing.status == "active",
            Listing.deal_type == deal_type,
            Listing.price_usd >= min_price_usd,
            Listing.price_per_m2_usd >= min_ppm,
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


@router.get("/complexes", response_model=ComplexStatsPage)
def get_complexes(
    db: Session = Depends(get_db),
    deal_type: Literal["sale", "rent"] = "sale",
    district: Optional[str] = None,
    sort: Literal["count", "median_ppm", "median_price"] = "count",
    limit: int = Query(300, ge=1, le=1000),
) -> ComplexStatsPage:
    """Агрегаты по ЖК (медиана цены/$м², число объявлений) — только ЖК с ≥порога
    листингов, иначе «средняя» это шум."""
    settings = get_settings()
    stats = list_complex_stats(db, settings, deal_type=deal_type, district=district, limit=limit)
    if sort == "median_ppm":
        stats.sort(key=lambda s: s.median_price_per_m2_usd)
    elif sort == "median_price":
        stats.sort(key=lambda s: s.median_price_usd)
    items = [ComplexStatOut(**s.__dict__) for s in stats]
    return ComplexStatsPage(items=items, total=len(items))


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
    item = _build_item(listing)
    _attach_complex_comparison(db, get_settings(), [listing], [item], listing.deal_type)
    return item
