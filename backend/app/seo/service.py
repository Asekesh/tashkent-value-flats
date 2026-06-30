"""Агрегации и данные для SEO-хабов + динамический sitemap.

Хаб — это срез активных объявлений по району и/или комнатности. Условия отбора
повторяют публичный API (api/listings): только status="active" и выше порогов
цены, чтобы на лендингах не светились мусорные/архивные строки.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, nulls_last, select
from sqlalchemy.orm import Session
from xml.sax.saxutils import escape

from app.core.config import Settings
from app.models import Listing
from app.seo.slugs import DISTRICT_SLUGS, rooms_slug
from app.services.normalization import loads_json

BASE_URL = "https://uyradar.uz"

# Хабы беднее этого порога не индексируем и не кладём в sitemap — защита от
# «thin content» (страница с одним объявлением Google посчитает мусором).
MIN_HUB_LISTINGS = 3
HUB_LIST_LIMIT = 48

SOURCE_LABELS = {"olx": "OLX", "uybor": "Uybor", "realt24": "Realt24"}


def fmt_usd(value: float | None) -> str:
    if value is None:
        return "—"
    return "$" + f"{int(round(value)):,}".replace(",", " ")


def fmt_num(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{int(round(value)):,}".replace(",", " ")


def base_conditions(settings: Settings, deal_type: str = "sale") -> list:
    min_price, min_ppm = settings.price_floors(deal_type)
    return [
        Listing.status == "active",
        Listing.deal_type == deal_type,
        Listing.price_usd >= min_price,
        Listing.price_per_m2_usd >= min_ppm,
    ]


def listing_card(listing: Listing) -> dict:
    """Плоская view-модель объявления для шаблона (ORM-объект в Jinja неудобен)."""
    photos = loads_json(listing.photos, [])
    return {
        "url": listing.url,
        "title": listing.title,
        "price_usd": listing.price_usd,
        "price_per_m2_usd": listing.price_per_m2_usd,
        "rooms": listing.rooms,
        "area_m2": listing.area_m2,
        "floor": listing.floor,
        "total_floors": listing.total_floors,
        "district": listing.district,
        "address": listing.address_raw,
        "photo": photos[0] if photos else None,
        "discount_percent": listing.discount_percent if listing.is_below_market else None,
        "source": listing.source,
        "source_label": SOURCE_LABELS.get(listing.source, listing.source.title()),
    }


@dataclass
class HubData:
    district: str | None
    rooms: int | None
    total: int
    min_price_usd: float | None
    avg_ppm_usd: float | None
    cards: list[dict] = field(default_factory=list)
    deal_type: str = "sale"
    price_period: str | None = None
    avg_price_usd: float | None = None  # средняя $/мес для аренды
    rooms_table: list[dict] = field(default_factory=list)  # заполняется в _render_hub


def load_hub(
    db: Session,
    settings: Settings,
    *,
    district: str | None = None,
    rooms: int | None = None,
    deal_type: str = "sale",
    limit: int = HUB_LIST_LIMIT,
) -> HubData:
    conds = base_conditions(settings, deal_type)
    if district:
        conds.append(Listing.district == district)
    if rooms:
        conds.append(Listing.rooms == rooms)

    total = db.scalar(select(func.count()).select_from(Listing).where(*conds)) or 0
    period = "month" if deal_type == "rent" else None
    if total == 0:
        return HubData(district, rooms, 0, None, None, [], deal_type, period, None)

    min_price = db.scalar(select(func.min(Listing.price_usd)).where(*conds))
    avg_ppm = db.scalar(select(func.avg(Listing.price_per_m2_usd)).where(*conds))
    avg_price = (
        db.scalar(select(func.avg(Listing.price_usd)).where(*conds))
        if deal_type == "rent"
        else None
    )
    # Лучшие сделки сверху: дисконт к рынку убыванием, затем дешевле по $/м².
    rows = db.scalars(
        select(Listing)
        .where(*conds)
        .order_by(
            nulls_last(Listing.discount_percent.desc()),
            Listing.price_per_m2_usd.asc(),
            Listing.id.asc(),
        )
        .limit(limit)
    ).all()
    return HubData(
        district, rooms, int(total), min_price, avg_ppm,
        [listing_card(r) for r in rows], deal_type, period, avg_price,
    )


def available_hubs(
    db: Session, settings: Settings, deal_type: str = "sale"
) -> tuple[dict[str, int], dict[int, int], dict[tuple[str, int], int]]:
    """Срезы с >= MIN_HUB_LISTINGS активных — для каталога и sitemap.

    Возвращает (районы, комнатность, район×комнатность) → счётчик. Только
    районы из карты slug'ов (без «Не указан») и комнатность 1..6.
    """
    conds = base_conditions(settings, deal_type)

    districts: dict[str, int] = {}
    for dist, cnt in db.execute(
        select(Listing.district, func.count()).where(*conds).group_by(Listing.district)
    ).all():
        if dist in DISTRICT_SLUGS and cnt >= MIN_HUB_LISTINGS:
            districts[dist] = int(cnt)

    rooms: dict[int, int] = {}
    for room, cnt in db.execute(
        select(Listing.rooms, func.count()).where(*conds).group_by(Listing.rooms)
    ).all():
        if room and 1 <= room <= 6 and cnt >= MIN_HUB_LISTINGS:
            rooms[int(room)] = int(cnt)

    combos: dict[tuple[str, int], int] = {}
    for dist, room, cnt in db.execute(
        select(Listing.district, Listing.rooms, func.count())
        .where(*conds)
        .group_by(Listing.district, Listing.rooms)
    ).all():
        if dist in DISTRICT_SLUGS and room and 1 <= room <= 6 and cnt >= MIN_HUB_LISTINGS:
            combos[(dist, int(room))] = int(cnt)

    return districts, rooms, combos


def rooms_breakdown(
    db: Session, settings: Settings, district: str, deal_type: str = "sale"
) -> list[dict]:
    """Средняя цена и кол-во по комнатности (1..5) в рамках района.

    Для продажи avg_price — средняя полная цена, для аренды — средняя $/мес.
    Используется на district-only хабе; на rooms-фиксированных не вызывается.
    """
    conds = base_conditions(settings, deal_type) + [Listing.district == district]
    rows = db.execute(
        select(Listing.rooms, func.count(), func.avg(Listing.price_usd))
        .where(*conds)
        .group_by(Listing.rooms)
        .order_by(Listing.rooms.asc())
    ).all()
    return [
        {"rooms": int(rm), "count": int(cnt), "avg_price": float(avg)}
        for rm, cnt, avg in rows
        if rm and 1 <= rm <= 5
    ]


# --- Sitemap -----------------------------------------------------------------

_STATIC_URLS = [
    ("/", "daily", "1.0"),
    ("/kvartira", "daily", "0.8"),
    ("/terms", "monthly", "0.3"),
    ("/disclaimer", "monthly", "0.3"),
    ("/removal", "monthly", "0.3"),
]


def _url_entry(path: str, lastmod: str, changefreq: str, priority: str) -> str:
    loc = escape(BASE_URL + path)
    return (
        "  <url>\n"
        f"    <loc>{loc}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        f"    <changefreq>{changefreq}</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        "  </url>"
    )


def build_sitemap_xml(db: Session, settings: Settings) -> str:
    """Собираем sitemap на лету: статические страницы + все доступные хабы.

    ~50-80 URL — на порядок ниже лимита 50 000, поэтому один файл без индекса.
    Строим на каждый запрос (несколько GROUP BY по индексированным колонкам);
    боты дёргают sitemap редко, кэш не нужен.
    """
    last_dt = db.scalar(select(func.max(Listing.updated_at)).where(*base_conditions(settings)))
    lastmod = (last_dt or datetime.utcnow()).strftime("%Y-%m-%d")

    districts, rooms, combos = available_hubs(db, settings)

    entries = [_url_entry(path, lastmod, freq, prio) for path, freq, prio in _STATIC_URLS]
    for dist in districts:
        entries.append(_url_entry(f"/kvartira/{DISTRICT_SLUGS[dist]}", lastmod, "daily", "0.7"))
    for room in rooms:
        entries.append(_url_entry(f"/kvartira/{rooms_slug(room)}", lastmod, "daily", "0.6"))
    for dist, room in combos:
        entries.append(
            _url_entry(f"/kvartira/{DISTRICT_SLUGS[dist]}/{rooms_slug(room)}", lastmod, "daily", "0.6")
        )

    body = "\n".join(entries)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )
