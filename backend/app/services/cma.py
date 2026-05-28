from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Listing
from app.services.listing_features import (
    extract_material,
    extract_micro_location,
    extract_year,
    floors_close,
    years_close,
)
from app.services.segmentation import classify_segment, is_extreme_floor


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
    basis: str  # "building" | "micro_location" | "district" | "district_relaxed" | "insufficient_data"
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
    """Подбор аналогов с каскадом «дом → массив/ЖК → район».

    Логика: район в Ташкенте идёт «лучами» от центра к краю — Феруза и Ц-1
    формально в одном районе, но это разные рынки. Поэтому строгий матч идёт
    по микро-локации (массив/ЖК/блок) с дополнительными фильтрами по сегменту,
    материалу стен, этажу и году постройки. Если строгий пул пуст —
    возвращаемся к району с ослабленными критериями, помечая базис.
    """
    settings = get_settings()
    min_area = listing.area_m2 * (1 - AREA_TOLERANCE)
    max_area = listing.area_m2 * (1 + AREA_TOLERANCE)

    subject_segment = classify_segment(listing.title, listing.address_raw, listing.description)
    subject_material = extract_material(listing.title, listing.description)
    subject_micro = extract_micro_location(listing.address_raw, listing.title, listing.description)
    subject_year = extract_year(listing.title, listing.description)
    subject_extreme = is_extreme_floor(listing.floor, listing.total_floors)

    base_filters = (
        Listing.status == "active",
        Listing.price_usd >= settings.min_listing_price_usd,
        Listing.price_per_m2_usd >= settings.min_listing_price_per_m2_usd,
        Listing.rooms == listing.rooms,
        Listing.area_m2 >= min_area,
        Listing.area_m2 <= max_area,
        Listing.id != listing.id,
    )

    pool: list[Listing] = list(db.scalars(select(Listing).where(*base_filters)).all())

    def passes_strict(c: Listing) -> bool:
        # Сегмент — всегда строго: новостройка и вторичка это разные рынки.
        if classify_segment(c.title, c.address_raw, c.description) != subject_segment:
            return False
        # Материал — строго, только если у subject он распознан. У кандидата
        # неизвестный материал не блокирует (нет данных != «другой материал»).
        if subject_material:
            c_material = extract_material(c.title, c.description)
            if c_material and c_material != subject_material:
                return False
        # Крайние этажи (1/последний) и средние — структурно разные цены,
        # не смешиваем. Внутри средних держим окно ±2 этажа.
        if is_extreme_floor(c.floor, c.total_floors) != subject_extreme:
            return False
        if not floors_close(listing.floor, c.floor):
            return False
        # Год постройки → класс жилья. ±15 лет = «та же эпоха».
        if not years_close(subject_year, extract_year(c.title, c.description)):
            return False
        return True

    strict_pool = [c for c in pool if passes_strict(c)]

    basis = "insufficient_data"
    basis_label = "недостаточно данных для подбора аналогов"
    candidates: list[Listing] = []

    if listing.building_key:
        same_building = [c for c in strict_pool if c.building_key == listing.building_key]
        if same_building:
            candidates = same_building
            basis = "building"
            basis_label = (
                f"тот же дом ({listing.address_raw or listing.district}), "
                f"{listing.rooms}-комн., схожие параметры"
            )

    if not candidates and subject_micro:
        same_micro = [
            c
            for c in strict_pool
            if c.district == listing.district
            and extract_micro_location(c.address_raw, c.title, c.description) == subject_micro
        ]
        if same_micro:
            candidates = same_micro
            basis = "micro_location"
            basis_label = (
                f"массив/ЖК «{subject_micro}», "
                f"{listing.rooms}-комн., схожие параметры"
            )

    if not candidates:
        same_district = [c for c in strict_pool if c.district == listing.district]
        if same_district:
            candidates = same_district
            basis = "district"
            basis_label = (
                f"район {listing.district}, {listing.rooms}-комн., "
                f"схожие параметры (сегмент/материал/этаж/год)"
            )

    if not candidates:
        # Строгий пул пуст — берём район без доп. фильтров, помечаем флагом.
        relaxed = [c for c in pool if c.district == listing.district]
        if relaxed:
            candidates = relaxed
            basis = "district_relaxed"
            basis_label = (
                f"район {listing.district}, ослабленные критерии "
                f"(точных аналогов не нашлось)"
            )

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
