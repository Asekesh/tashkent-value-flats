from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Listing
from app.services.segmentation import (
    SEGMENT_SECONDARY,
    classify_segment,
    is_extreme_floor,
)


# Sanity-check для рынка $/м² в Ташкенте. Реальный диапазон ~$500-1500/м²;
# границы расширены, но любая «средняя» вне этого окна — мусорные данные
# (опечатки, фейки, перепутанная валюта/площадь).
MARKET_PRICE_MIN_USD_PER_M2 = 400.0
MARKET_PRICE_MAX_USD_PER_M2 = 3000.0

# Дисконт > 30% — почти всегда либо битое объявление, либо квартира другой
# категории (старый фонд против новостроек, дефект, спорная история).
# В реальной недвиге сделка -30% это уже редкая удача; всё что глубже
# показывать как «горячее» не стоит — это ломает доверие к продукту.
MAX_REALISTIC_DISCOUNT_PERCENT = 30.0

# Минимальные выборки. Building+rooms строже: при <5 одно бракованное
# объявление перетягивает медиану и даёт фейковый «дисконт». Район
# усредняет по сотням объявлений — можно мягче.
MIN_BUILDING_ROOM_SAMPLES = 5
MIN_DISTRICT_ROOM_SAMPLES = 3


@dataclass
class Estimate:
    market_price_per_m2_usd: float | None
    sample_size: int
    basis: str
    confidence: str
    discount_percent: float | None
    is_below_market: bool
    savings_usd: float | None


@dataclass
class MarketIndex:
    """Предрассчитанные медианы по активной базе.

    Используется и `/listings`, и `/listings/stats`, чтобы числа на дашборде и
    в списке считались по одной формуле. Ключ включает сегмент (новостройка/
    вторичка): хрущёвки и новостройки в одном районе — разные рынки,
    смешивание их медиан даёт ложные «-50% от рынка» на старом фонде.
    """

    # (building_key, rooms, segment) -> (median_ppm, n)
    building_rooms: dict[tuple[str, int, str], tuple[float, int]] = field(default_factory=dict)
    # (district, rooms, segment) -> (median_ppm, n)
    district_rooms: dict[tuple[str, int, str], tuple[float, int]] = field(default_factory=dict)


def _robust_price(values: list[float], min_samples: int) -> float | None:
    """Trimmed median с sanity-check. Возвращает None если данных мало
    или результат выпал из разумных границ для Ташкента."""
    if len(values) < min_samples:
        return None
    sorted_vals = sorted(values)
    if len(sorted_vals) >= 10:
        trim = len(sorted_vals) // 10
        sorted_vals = sorted_vals[trim : len(sorted_vals) - trim]
    price = float(median(sorted_vals))
    if not (MARKET_PRICE_MIN_USD_PER_M2 <= price <= MARKET_PRICE_MAX_USD_PER_M2):
        return None
    return price


def build_market_index(db: Session) -> MarketIndex:
    settings = get_settings()
    rows = db.execute(
        select(
            Listing.district,
            Listing.rooms,
            Listing.building_key,
            Listing.price_per_m2_usd,
            Listing.title,
            Listing.address_raw,
            Listing.description,
            Listing.floor,
            Listing.total_floors,
        ).where(
            Listing.status == "active",
            Listing.price_usd >= settings.min_listing_price_usd,
            Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
        )
    ).all()
    building_room_groups: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    district_room_groups: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    for row in rows:
        if row.price_per_m2_usd is None or row.rooms is None:
            continue
        # Отсекаем выбросы на уровне сырых данных, чтобы они даже не попадали
        # в выборку для медианы. $32k/м² в одном объявлении — это либо опечатка,
        # либо стартовая цена для торга, не рынок.
        if not (MARKET_PRICE_MIN_USD_PER_M2 <= row.price_per_m2_usd <= MARKET_PRICE_MAX_USD_PER_M2):
            continue
        # Крайние этажи (1-й и последний) системно дешевле на 15-25%. Если
        # оставить их в базе — медиана уезжает вниз, и обычные квартиры
        # начинают выглядеть «выше рынка», а сами 1-е этажи — «по рынку».
        if is_extreme_floor(row.floor, row.total_floors):
            continue
        segment = classify_segment(row.title, row.address_raw, row.description)
        if row.building_key:
            building_room_groups[(row.building_key, row.rooms, segment)].append(row.price_per_m2_usd)
        if row.district:
            district_room_groups[(row.district, row.rooms, segment)].append(row.price_per_m2_usd)

    building_rooms: dict[tuple[str, int, str], tuple[float, int]] = {}
    for key, values in building_room_groups.items():
        price = _robust_price(values, MIN_BUILDING_ROOM_SAMPLES)
        if price is not None:
            building_rooms[key] = (price, len(values))

    district_rooms: dict[tuple[str, int, str], tuple[float, int]] = {}
    for key, values in district_room_groups.items():
        price = _robust_price(values, MIN_DISTRICT_ROOM_SAMPLES)
        if price is not None:
            district_rooms[key] = (price, len(values))

    return MarketIndex(building_rooms=building_rooms, district_rooms=district_rooms)


def estimate_from_index(
    index: MarketIndex,
    *,
    building_key: str | None,
    district: str,
    rooms: int,
    area_m2: float | None,
    listing_price_per_m2: float | None,
    segment: str | None = None,
    floor: int | None = None,
    total_floors: int | None = None,
) -> Estimate:
    market_price: float | None = None
    sample_size = 0
    basis = "insufficient_data"
    confidence = "low"

    seg = segment or SEGMENT_SECONDARY

    if building_key and (building_key, rooms, seg) in index.building_rooms:
        price, count = index.building_rooms[(building_key, rooms, seg)]
        market_price = round(price, 2)
        sample_size = count
        basis = "building"
        confidence = "high" if count >= 10 else "medium"
    elif (district, rooms, seg) in index.district_rooms:
        price, count = index.district_rooms[(district, rooms, seg)]
        market_price = round(price, 2)
        sample_size = count
        basis = "district_rooms"
        confidence = "medium" if count >= 10 else "low"

    discount: float | None = None
    savings: float | None = None
    is_below = False
    # Для 1-го/последнего этажа дисконт не считаем: база для них ненадёжна
    # (мы их выкинули из медианы), а сравнивать с медианой обычных этажей
    # бессмысленно — структурный дисконт этажа выглядел бы как «скидка».
    extreme = is_extreme_floor(floor, total_floors)
    if market_price and listing_price_per_m2 and market_price > 0 and not extreme:
        raw_discount = (1 - listing_price_per_m2 / market_price) * 100
        if raw_discount > MAX_REALISTIC_DISCOUNT_PERCENT:
            # Скам / опечатка / неучтённая категория — не показываем
            # фейковый дисконт, объявление просто не попадёт в «горячие».
            discount = None
        else:
            discount = round(raw_discount, 2)
            threshold = get_settings().below_market_threshold * 100
            is_below = discount >= threshold
            if area_m2:
                savings = round((market_price - listing_price_per_m2) * area_m2, 2)

    return Estimate(
        market_price_per_m2_usd=market_price,
        sample_size=sample_size,
        basis=basis,
        confidence=confidence,
        discount_percent=discount,
        is_below_market=is_below,
        savings_usd=savings,
    )


def estimate_market(
    db: Session,
    *,
    district: str,
    rooms: int,
    area_m2: float,
    building_key: str | None = None,
    listing_price_per_m2: float | None = None,
    segment: str | None = None,
    floor: int | None = None,
    total_floors: int | None = None,
    exclude_listing_id: int | None = None,  # noqa: ARG001 — оставлено для совместимости вызовов
) -> Estimate:
    """Оценка для одного объявления — использует тот же индекс, что и листинг/статистика."""
    index = build_market_index(db)
    return estimate_from_index(
        index,
        building_key=building_key,
        district=district,
        rooms=rooms,
        area_m2=area_m2,
        listing_price_per_m2=listing_price_per_m2,
        segment=segment,
        floor=floor,
        total_floors=total_floors,
    )
