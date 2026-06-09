"""Доходность от сдачи в аренду (gross rental yield) для листинга на продажу.

Идея: у нас в одной таблице и продажа, и аренда. Сопоставив цену продажи с
типичной арендой того же места/типоразмера, получаем «если купить и сдавать —
сколько процентов годовых / за сколько лет окупится». Этого никто на рынке
Ташкента не показывает, а ядро аудитории — инвесторы.

Доходность валовая (до налогов, простоя, расходов) — так и подписываем во
фронте. Считаем в $/м²: arenda_ppm_в_месяц·12 / cena_ppm = годовая_аренда/цена,
площадь сокращается. Цена берётся ИЗ листинга (что реально платит покупатель),
поэтому недооценённый лот честно показывает доходность выше — это и есть хук.

Каскад привязки арендной медианы: тот же ЖК + комнатность → район + комнатность.
Где данных аренды мало — цифру просто не показываем (фича «зажигается» по мере
накопления аренды, см. [complex_stats] про покрытие).

Сервис отделён намеренно: доходность планируется как платная фича, поэтому
[attach_rental_yield] — единственная точка, которую позже закроет авторизация.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Listing

# Медиана аренды по <N объявлений — шум: один «евроремонт под ключ» перетягивает.
YIELD_MIN_SAMPLES = 5
# Валовая доходность жилья в Ташкенте реально ~4–10%, у дешёвого сегмента/студий
# выше. Всё вне 1–20% — почти всегда рассогласованные данные (аренда из другого
# сегмента, перепутанный период, битая цена). Не показываем, чтобы не подрывать
# доверие к платной цифре.
YIELD_MIN_PERCENT = 1.0
YIELD_MAX_PERCENT = 20.0


@dataclass
class RentalYield:
    gross_yield_percent: float
    payback_years: float
    rent_median_ppm_month: float  # медиана аренды $/м²/мес, на которой посчитано
    basis: str  # "complex" | "district"
    sample_size: int


def _rent_medians(
    db: Session,
    settings: Settings,
    *,
    complex_ids: set[int],
    districts: set[str],
) -> tuple[dict[tuple[int, int], tuple[float, int]], dict[tuple[str, int], tuple[float, int]]]:
    """Батч: медианы аренды $/м²/мес по (ЖК, комнаты) и (район, комнаты).

    Один проход по активной аренде, попадающей в ЖК ИЛИ районы текущей страницы —
    чтобы повесить доходность на лист без N+1. Те же пороги вменяемости и стенка
    deal_type='rent', что и везде."""
    if not complex_ids and not districts:
        return {}, {}
    min_price, min_ppm = settings.price_floors("rent")
    scope = []
    if complex_ids:
        scope.append(Listing.residential_complex_id.in_(complex_ids))
    if districts:
        scope.append(Listing.district.in_(districts))
    rows = db.execute(
        select(
            Listing.residential_complex_id,
            Listing.district,
            Listing.rooms,
            Listing.price_per_m2_usd,
        ).where(
            Listing.status == "active",
            Listing.deal_type == "rent",
            Listing.price_usd >= min_price,
            Listing.price_per_m2_usd >= min_ppm,
            or_(*scope),
        )
    ).all()

    by_cr: dict[tuple[int, int], list[float]] = defaultdict(list)
    by_dr: dict[tuple[str, int], list[float]] = defaultdict(list)
    for rc_id, district, rooms, ppm in rows:
        if rooms is None or not ppm:
            continue
        if rc_id is not None:
            by_cr[(rc_id, rooms)].append(ppm)
        if district:
            by_dr[(district, rooms)].append(ppm)

    def reduce(groups):
        return {
            key: (round(float(median(vals)), 3), len(vals))
            for key, vals in groups.items()
            if len(vals) >= YIELD_MIN_SAMPLES
        }

    return reduce(by_cr), reduce(by_dr)


def _compute(sale_ppm: float, rent_ppm_month: float, basis: str, sample_size: int) -> Optional[RentalYield]:
    """Валовая доходность из цены продажи ($/м²) и аренды ($/м²/мес). None —
    если результат вне разумных границ (рассогласованные данные)."""
    if not sale_ppm or sale_ppm <= 0 or not rent_ppm_month or rent_ppm_month <= 0:
        return None
    gross = rent_ppm_month * 12 / sale_ppm * 100
    if not (YIELD_MIN_PERCENT <= gross <= YIELD_MAX_PERCENT):
        return None
    return RentalYield(
        gross_yield_percent=round(gross, 1),
        payback_years=round(100 / gross, 1),
        rent_median_ppm_month=rent_ppm_month,
        basis=basis,
        sample_size=sample_size,
    )


def yield_for_sale_listing(
    db: Session,
    settings: Settings,
    listing: Listing,
) -> Optional[RentalYield]:
    """Доходность для одного листинга на продажу (детальная карточка)."""
    if listing.deal_type != "sale" or not listing.price_per_m2_usd:
        return None
    cids = {listing.residential_complex_id} if listing.residential_complex_id else set()
    dists = {listing.district} if listing.district else set()
    by_cr, by_dr = _rent_medians(db, settings, complex_ids=cids, districts=dists)
    return _cascade(listing, by_cr, by_dr)


def _cascade(listing: Listing, by_cr: dict, by_dr: dict) -> Optional[RentalYield]:
    """ЖК+комнаты (точнее) → район+комнаты (шире). Цена — из самого листинга."""
    if listing.rooms is None:
        return None
    if listing.residential_complex_id is not None:
        hit = by_cr.get((listing.residential_complex_id, listing.rooms))
        if hit:
            return _compute(listing.price_per_m2_usd, hit[0], "complex", hit[1])
    if listing.district:
        hit = by_dr.get((listing.district, listing.rooms))
        if hit:
            return _compute(listing.price_per_m2_usd, hit[0], "district", hit[1])
    return None


def yields_for_rows(db: Session, settings: Settings, rows, deal_type: str) -> dict[int, RentalYield]:
    """Доходность для пачки sale-листингов (батч, без N+1) → {listing_id: RentalYield}.

    Единая точка фичи: для аренды пусто; позже здесь же встанет гейт платного
    доступа (не считать/не отдавать неоплатившим)."""
    if deal_type != "sale":
        return {}
    complex_ids = {r.residential_complex_id for r in rows if r.residential_complex_id is not None}
    districts = {r.district for r in rows if r.district}
    by_cr, by_dr = _rent_medians(db, settings, complex_ids=complex_ids, districts=districts)
    if not by_cr and not by_dr:
        return {}
    out: dict[int, RentalYield] = {}
    for row in rows:
        ry = _cascade(row, by_cr, by_dr)
        if ry is not None:
            out[row.id] = ry
    return out
