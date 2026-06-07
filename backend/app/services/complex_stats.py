"""Агрегаты по ЖК: медиана цены/$м² и сравнение конкретного листинга со своим ЖК.

Опирается на чистый справочник (см. нормализатор/ремердж в [normalization]/[listings]).
Считаем по-Python-медиане (а не percentile_cont) — кросс-диалектно (Postgres прод /
SQLite тесты) и дёшево: у ЖК десятки листингов, всего активных-с-ЖК ~6k.

Порог COMPLEX_MIN_LISTINGS: ЖК с <N листингами не показываем/не сравниваем —
медиана по 1-2 объявлениям это шум (см. разведку покрытия: 229 ЖК с ≥5 держат 61%
размеченных)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Listing, ResidentialComplex

COMPLEX_MIN_LISTINGS = 5


@dataclass
class ComplexStat:
    id: int
    name: str
    district: Optional[str]
    deal_type: str
    count: int
    median_price_usd: float
    median_price_per_m2_usd: float
    min_price_usd: float


@dataclass
class ComplexComparison:
    name: str
    count: int
    median_price_per_m2_usd: float
    vs_complex_percent: Optional[float]  # >0 = листинг ДЕШЕВЛЕ медианы ЖК (как discount)
    is_below_complex: bool


def _sane_conditions(settings: Settings, deal_type: str) -> list:
    """Те же пороги вменяемости и стенка deal_type, что и везде в приложении —
    чтобы медиана ЖК считалась по тем же листингам, что видит юзер."""
    min_price, min_ppm = settings.price_floors(deal_type)
    return [
        Listing.status == "active",
        Listing.deal_type == deal_type,
        Listing.residential_complex_id.is_not(None),
        Listing.price_usd >= min_price,
        Listing.price_per_m2_usd >= min_ppm,
    ]


def list_complex_stats(
    db: Session,
    settings: Settings,
    *,
    deal_type: str = "sale",
    district: Optional[str] = None,
    min_listings: int = COMPLEX_MIN_LISTINGS,
    limit: int = 300,
) -> list[ComplexStat]:
    """Список ЖК с агрегатами (для /api/complexes). Только ЖК с ≥min_listings."""
    conds = _sane_conditions(settings, deal_type)
    if district:
        conds.append(Listing.district == district)
    rows = db.execute(
        select(Listing.residential_complex_id, Listing.price_usd, Listing.price_per_m2_usd).where(*conds)
    ).all()
    groups: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for rc_id, price, ppm in rows:
        groups[rc_id].append((price, ppm))
    qualifying = {rc_id: vals for rc_id, vals in groups.items() if len(vals) >= min_listings}
    if not qualifying:
        return []
    meta = {
        rc.id: (rc.name, rc.district)
        for rc in db.scalars(
            select(ResidentialComplex).where(ResidentialComplex.id.in_(qualifying.keys()))
        ).all()
    }
    stats: list[ComplexStat] = []
    for rc_id, vals in qualifying.items():
        name_district = meta.get(rc_id)
        if not name_district:
            continue
        name, dist = name_district
        prices = [p for p, _ in vals]
        ppms = [m for _, m in vals]
        stats.append(
            ComplexStat(
                id=rc_id,
                name=name,
                district=dist,
                deal_type=deal_type,
                count=len(vals),
                median_price_usd=round(float(median(prices)), 2),
                median_price_per_m2_usd=round(float(median(ppms)), 2),
                min_price_usd=round(float(min(prices)), 2),
            )
        )
    stats.sort(key=lambda s: (-s.count, s.name))
    return stats[:limit]


def complex_comparison_map(
    db: Session,
    settings: Settings,
    *,
    rc_ids: list[int],
    deal_type: str,
    min_listings: int = COMPLEX_MIN_LISTINGS,
) -> dict[int, tuple[str, int, float]]:
    """{rc_id: (имя, count, median_ppm)} для ЖК из rc_ids с ≥min_listings листингами.
    Батч — один проход, чтобы повесить сравнение на страницу листингов без N+1."""
    unique = {i for i in rc_ids if i is not None}
    if not unique:
        return {}
    conds = _sane_conditions(settings, deal_type)
    conds.append(Listing.residential_complex_id.in_(unique))
    rows = db.execute(
        select(Listing.residential_complex_id, Listing.price_per_m2_usd).where(*conds)
    ).all()
    groups: dict[int, list[float]] = defaultdict(list)
    for rc_id, ppm in rows:
        groups[rc_id].append(ppm)
    eligible = {rc_id: ppms for rc_id, ppms in groups.items() if len(ppms) >= min_listings}
    if not eligible:
        return {}
    names = {
        rc.id: rc.name
        for rc in db.scalars(
            select(ResidentialComplex).where(ResidentialComplex.id.in_(eligible.keys()))
        ).all()
    }
    return {
        rc_id: (names.get(rc_id, ""), len(ppms), round(float(median(ppms)), 2))
        for rc_id, ppms in eligible.items()
        if names.get(rc_id)
    }


def build_comparison(
    listing_ppm: Optional[float],
    name: str,
    count: int,
    median_ppm: float,
    *,
    below_threshold_percent: float,
) -> ComplexComparison:
    """Сравнение листинга с медианой его ЖК. vs%>0 = дешевле медианы."""
    vs: Optional[float] = None
    is_below = False
    if listing_ppm and median_ppm > 0:
        vs = round((1 - listing_ppm / median_ppm) * 100, 1)
        is_below = vs >= below_threshold_percent
    return ComplexComparison(
        name=name,
        count=count,
        median_price_per_m2_usd=median_ppm,
        vs_complex_percent=vs,
        is_below_complex=is_below,
    )
