"""SEO-хабы: серверные лендинги по районам и комнатности + sitemap.

Маршруты:
  /kvartira                         — каталог (все районы и комнатность)
  /kvartira/{slug}                  — район ИЛИ «N-komnatnye» (по всему городу)
  /kvartira/{district}/{rooms}      — район + комнатность
  /sitemap.xml                      — динамический sitemap

Слаги-комнатности (^\\d-komnatnye$) и слаги-районы не пересекаются, поэтому
один маршрут /kvartira/{slug} разводит их по виду внутри обработчика.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.seo import service
from app.seo.service import BASE_URL, ComplexHub, HubData, fmt_num, fmt_usd
from app.seo.slugs import (
    DISTRICT_SLUGS,
    complex_id_from_slug,
    complex_slug,
    district_from_slug,
    district_locative,
    rooms_from_slug,
    rooms_label,
    rooms_slug,
)
from app.services.complex_stats import list_complex_stats

router = APIRouter(tags=["seo"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["usd"] = fmt_usd
templates.env.filters["num"] = fmt_num

PREFIX = {"sale": "/kvartira", "rent": "/arenda"}
ROOT_LABEL = {"sale": "Квартиры", "rent": "Аренда"}


def _canonical(request: Request) -> str:
    return BASE_URL + request.url.path


def _breadcrumbs(data: HubData) -> list[dict]:
    pre = PREFIX[data.deal_type]
    crumbs = [{"name": "Главная", "url": "/"}, {"name": ROOT_LABEL[data.deal_type], "url": pre}]
    if data.district:
        crumbs.append({"name": data.district, "url": f"{pre}/{DISTRICT_SLUGS[data.district]}"})
        if data.rooms:
            crumbs.append(
                {
                    "name": rooms_label(data.rooms),
                    "url": f"{pre}/{DISTRICT_SLUGS[data.district]}/{rooms_slug(data.rooms)}",
                }
            )
    elif data.rooms:
        crumbs.append({"name": rooms_label(data.rooms), "url": f"{pre}/{rooms_slug(data.rooms)}"})
    return crumbs


def _related(db: Session, settings, data: HubData) -> list[dict]:
    """Блоки перелинковки — только реально существующие срезы."""
    districts, rooms, combos = service.available_hubs(db, settings, data.deal_type)
    pre = PREFIX[data.deal_type]
    sections: list[dict] = []

    if data.district and not data.rooms:
        # район → его комнатность + другие районы
        links = [
            {"label": f"{rooms_label(rm)} в этом районе", "url": f"{pre}/{DISTRICT_SLUGS[data.district]}/{rooms_slug(rm)}"}
            for (dist, rm) in sorted(combos) if dist == data.district
        ]
        if links:
            sections.append({"title": "По комнатности", "links": links})
        sections.append({"title": "Другие районы", "links": _district_links(districts, pre, exclude=data.district)})
    elif data.rooms and not data.district:
        # комнатность по городу → та же комнатность по районам + другая комнатность
        links = [
            {"label": dist, "url": f"{pre}/{DISTRICT_SLUGS[dist]}/{rooms_slug(data.rooms)}"}
            for (dist, rm) in sorted(combos) if rm == data.rooms
        ]
        if links:
            sections.append({"title": f"{rooms_label(data.rooms)} по районам", "links": links})
        sections.append({"title": "Другая комнатность", "links": _room_links(rooms, pre, exclude=data.rooms)})
    elif data.district and data.rooms:
        # район+комнатность → другая комнатность здесь + этот же тип в других районах
        other_rooms = [
            {"label": rooms_label(rm), "url": f"{pre}/{DISTRICT_SLUGS[data.district]}/{rooms_slug(rm)}"}
            for (dist, rm) in sorted(combos) if dist == data.district and rm != data.rooms
        ]
        if other_rooms:
            sections.append({"title": f"Другая комнатность в {district_locative(data.district)}", "links": other_rooms})
        other_dist = [
            {"label": dist, "url": f"{pre}/{DISTRICT_SLUGS[dist]}/{rooms_slug(data.rooms)}"}
            for (dist, rm) in sorted(combos) if rm == data.rooms and dist != data.district
        ]
        if other_dist:
            sections.append({"title": f"{rooms_label(data.rooms)} в других районах", "links": other_dist})
    return sections


def _district_links(districts: dict[str, int], pre: str, exclude: str | None = None) -> list[dict]:
    return [
        {"label": dist, "url": f"{pre}/{DISTRICT_SLUGS[dist]}"}
        for dist in sorted(districts) if dist != exclude
    ]


def _room_links(rooms: dict[int, int], pre: str, exclude: int | None = None) -> list[dict]:
    return [
        {"label": rooms_label(rm), "url": f"{pre}/{rooms_slug(rm)}"}
        for rm in sorted(rooms) if rm != exclude
    ]


def _meta(data: HubData) -> tuple[str, str, str]:
    """(h1, title, meta_description) для трёх видов хаба, по типу сделки."""
    if data.deal_type == "rent":
        return _meta_rent(data)
    return _meta_sale(data)


def _meta_sale(data: HubData) -> tuple[str, str, str]:
    if data.district and data.rooms:
        place = district_locative(data.district)
        h1 = f"{rooms_label(data.rooms)} квартиры в {place}"
        title = f"{h1} — {data.total} объявлений | uyradar.uz"
        desc = (
            f"{data.total} объявлений: {rooms_label(data.rooms).lower()} квартиры в {place} Ташкента. "
            f"Цены от {fmt_usd(data.min_price_usd)}, в среднем {fmt_num(data.avg_ppm_usd)} $/м². "
            "OLX, Uybor и Realt24 в одном месте с оценкой ниже рынка."
        )
    elif data.district:
        place = district_locative(data.district)
        h1 = f"Квартиры в {place}"
        title = f"{h1} — {data.total} объявлений от {fmt_usd(data.min_price_usd)} | uyradar.uz"
        desc = (
            f"{data.total} квартир на продажу в {place} Ташкента. Цены от {fmt_usd(data.min_price_usd)}, "
            f"в среднем {fmt_num(data.avg_ppm_usd)} $/м². Объявления с OLX, Uybor и Realt24 с оценкой ниже рынка."
        )
    else:  # rooms-only
        h1 = f"{rooms_label(data.rooms)} квартиры в Ташкенте"
        title = f"{h1} — {data.total} объявлений | uyradar.uz"
        desc = (
            f"{data.total} объявлений: {rooms_label(data.rooms).lower()} квартиры в Ташкенте. "
            f"Цены от {fmt_usd(data.min_price_usd)}, в среднем {fmt_num(data.avg_ppm_usd)} $/м². "
            "OLX, Uybor и Realt24 с оценкой ниже рынка."
        )
    return h1, title, desc


def _meta_rent(data: HubData) -> tuple[str, str, str]:
    pm = f"{fmt_usd(data.min_price_usd)}/мес"
    if data.district and data.rooms:
        place = district_locative(data.district)
        h1 = f"Аренда {data.rooms}-комнатных квартир в {place}"
        title = f"{h1} — {data.total} объявлений от {pm} | uyradar.uz"
        desc = (
            f"{data.total} объявлений: снять {data.rooms}-комнатную квартиру в {place} Ташкента. "
            f"Аренда от {pm}, в среднем {fmt_usd(data.avg_price_usd)}/мес. OLX и Uybor с оценкой ниже рынка."
        )
    elif data.district:
        place = district_locative(data.district)
        h1 = f"Аренда квартир в {place}"
        title = f"{h1} — {data.total} объявлений от {pm} | uyradar.uz"
        desc = (
            f"{data.total} квартир в аренду в {place} Ташкента. Аренда от {pm}, "
            f"в среднем {fmt_usd(data.avg_price_usd)}/мес. Объявления с OLX и Uybor с оценкой ниже рынка."
        )
    else:  # rooms-only
        h1 = f"Аренда {data.rooms}-комнатных квартир в Ташкенте"
        title = f"{h1} — {data.total} объявлений от {pm} | uyradar.uz"
        desc = (
            f"{data.total} объявлений: снять {data.rooms}-комнатную квартиру в Ташкенте. "
            f"Аренда от {pm}, в среднем {fmt_usd(data.avg_price_usd)}/мес. OLX и Uybor с оценкой ниже рынка."
        )
    return h1, title, desc


def _stats(data: HubData) -> list[dict]:
    items = [{"value": fmt_num(data.total), "label": "объявлений"}]
    if data.deal_type == "rent":
        items.append({"value": f"{fmt_usd(data.min_price_usd)}/мес", "label": "аренда от"})
        items.append({"value": f"{fmt_usd(data.avg_price_usd)}/мес", "label": "в среднем"})
    else:
        items.append({"value": fmt_usd(data.min_price_usd), "label": "цена от"})
        items.append({"value": f"{fmt_num(data.avg_ppm_usd)} $/м²", "label": "в среднем"})
    return items


def _intro(data: HubData) -> str:
    place = f"в {district_locative(data.district)}" if data.district else "в Ташкенте"
    rlabel = f"{data.rooms}-комнатных " if data.rooms else ""
    below = sum(1 for c in data.cards if c.get("discount_percent"))
    below_txt = f" {below} предложений ниже рыночной оценки." if below else ""
    if data.deal_type == "rent":
        return (
            f"Сейчас {data.total} {rlabel}квартир в аренду {place}. "
            f"Аренда от {fmt_usd(data.min_price_usd)}/мес, в среднем {fmt_usd(data.avg_price_usd)}/мес."
            f"{below_txt}"
        )
    return (
        f"Сейчас {data.total} {rlabel}квартир в продаже {place}. "
        f"Цены от {fmt_usd(data.min_price_usd)}, в среднем {fmt_num(data.avg_ppm_usd)} $/м²."
        f"{below_txt}"
    )


def _faq(data: HubData) -> list[dict]:
    place = district_locative(data.district) if data.district else "Ташкенте"
    rlabel = f"{data.rooms}-комнатную квартиру" if data.rooms else "квартиру"
    verb = "снять" if data.deal_type == "rent" else "купить"
    if data.deal_type == "rent":
        price_a = (
            f"Аренда от {fmt_usd(data.min_price_usd)}/мес, "
            f"в среднем {fmt_usd(data.avg_price_usd)}/мес по {data.total} объявлениям."
        )
    else:
        price_a = (
            f"Цены от {fmt_usd(data.min_price_usd)}, "
            f"в среднем {fmt_num(data.avg_ppm_usd)} $/м² по {data.total} объявлениям."
        )
    return [
        {"q": f"Сколько стоит {verb} {rlabel} в {place}?", "a": price_a},
        {"q": "Сколько объявлений доступно?",
         "a": f"В подборке {data.total} активных объявлений с OLX, Uybor и Realt24, обновляется ежедневно."},
        {"q": "Как выбрать вариант ниже рынка?",
         "a": "Объявления отсортированы по скидке к нашей оценке: лучшие сделки сверху, бейдж «−X% к рынку»."},
    ]


def _itemlist_jsonld(data: HubData) -> str | None:
    if not data.cards:
        return None
    items = []
    for i, c in enumerate(data.cards):
        node = {"@type": "RealEstateListing", "name": c["title"], "url": c["url"]}
        if c.get("price_usd"):
            node["offers"] = {
                "@type": "Offer",
                "price": int(round(c["price_usd"])),
                "priceCurrency": "USD",
            }
        items.append({"@type": "ListItem", "position": i + 1, "item": node})
    return json.dumps(
        {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items},
        ensure_ascii=False,
    )


def _faq_jsonld(faq: list[dict]) -> str | None:
    if not faq:
        return None
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in faq
            ],
        },
        ensure_ascii=False,
    )


def _breadcrumb_jsonld(request: Request, crumbs: list[dict]) -> str:
    items = [
        {
            "@type": "ListItem",
            "position": i + 1,
            "name": c["name"],
            "item": BASE_URL + c["url"],
        }
        for i, c in enumerate(crumbs)
    ]
    data = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}
    return json.dumps(data, ensure_ascii=False)


def _cross_link(db: Session, settings, data: HubData) -> dict | None:
    """Ссылка на зеркальный срез в другом deal_type, если он непустой."""
    other = "rent" if data.deal_type == "sale" else "sale"
    other_data = service.load_hub(
        db, settings, district=data.district, rooms=data.rooms, deal_type=other
    )
    if other_data.total == 0:
        return None
    pre = PREFIX[other]
    if data.district and data.rooms:
        url = f"{pre}/{DISTRICT_SLUGS[data.district]}/{rooms_slug(data.rooms)}"
    elif data.district:
        url = f"{pre}/{DISTRICT_SLUGS[data.district]}"
    elif data.rooms:
        url = f"{pre}/{rooms_slug(data.rooms)}"
    else:
        url = pre
    place = district_locative(data.district) if data.district else "Ташкенте"
    label = f"Снять в {place}" if other == "rent" else f"Купить в {place}"
    return {"url": url, "label": label, "count": other_data.total}


def _render_hub(request: Request, db: Session, settings, data: HubData) -> HTMLResponse:
    h1, title, desc = _meta(data)
    crumbs = _breadcrumbs(data)
    # Таблица по комнатности — только на district-only хабе.
    if data.district and not data.rooms:
        data.rooms_table = service.rooms_breakdown(db, settings, data.district, data.deal_type)
    faq = _faq(data)
    jsonld_extra = [j for j in (_itemlist_jsonld(data), _faq_jsonld(faq)) if j]
    context = {
        "page_title": title,
        "meta_description": desc,
        "canonical": _canonical(request),
        "h1": h1,
        "data": data,
        "stats": _stats(data),
        "intro": _intro(data),
        "faq": faq,
        "breadcrumbs": crumbs,
        "related": _related(db, settings, data),
        "cross_link": _cross_link(db, settings, data),
        "jsonld": _breadcrumb_jsonld(request, crumbs),
        "jsonld_extra": jsonld_extra,
        "og_image": f"{BASE_URL}/static/logo.png",
    }
    return templates.TemplateResponse(request, "hub.html", context)


def _catalog(request: Request, db: Session, deal_type: str) -> HTMLResponse:
    settings = get_settings()
    districts, rooms, _ = service.available_hubs(db, settings, deal_type)
    pre = PREFIX[deal_type]
    if deal_type == "rent":
        h1 = "Аренда квартир в Ташкенте по районам"
        page_title = "Аренда квартир в Ташкенте по районам — каталог | uyradar.uz"
        meta = (
            "Каталог аренды квартир в Ташкенте по районам и комнатности: Чиланзар, Юнусабад, "
            "Мирабад и другие. Объявления с OLX и Uybor с оценкой ниже рынка."
        )
    else:
        h1 = "Квартиры в Ташкенте по районам"
        page_title = "Квартиры в Ташкенте по районам — каталог | uyradar.uz"
        meta = (
            "Каталог квартир в Ташкенте по районам и комнатности: Чиланзар, Юнусабад, "
            "Мирабад и другие. Объявления с OLX, Uybor и Realt24 с оценкой ниже рынка."
        )
    context = {
        "h1": h1,
        "page_title": page_title,
        "meta_description": meta,
        "canonical": _canonical(request),
        "district_links": _district_links(districts, pre),
        "room_links": _room_links(rooms, pre),
        "jsonld": _breadcrumb_jsonld(
            request, [{"name": "Главная", "url": "/"}, {"name": ROOT_LABEL[deal_type], "url": pre}]
        ),
        "jsonld_extra": [],
        "og_image": f"{BASE_URL}/static/logo.png",
    }
    return templates.TemplateResponse(request, "catalog.html", context)


@router.get("/kvartira", response_class=HTMLResponse, include_in_schema=False)
def catalog(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _catalog(request, db, "sale")


@router.get("/arenda", response_class=HTMLResponse, include_in_schema=False)
def rent_catalog(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _catalog(request, db, "rent")


def _slug_hub(slug: str, request: Request, db: Session, deal_type: str) -> HTMLResponse:
    settings = get_settings()
    rooms = rooms_from_slug(slug)
    if rooms is not None:
        data = service.load_hub(db, settings, rooms=rooms, deal_type=deal_type)
    else:
        district = district_from_slug(slug)
        if not district:
            raise HTTPException(status_code=404, detail="Страница не найдена")
        data = service.load_hub(db, settings, district=district, deal_type=deal_type)
    if data.total == 0:
        raise HTTPException(status_code=404, detail="Нет активных объявлений")
    return _render_hub(request, db, settings, data)


def _district_rooms_hub(
    dslug: str, rslug: str, request: Request, db: Session, deal_type: str
) -> HTMLResponse:
    settings = get_settings()
    district = district_from_slug(dslug)
    rooms = rooms_from_slug(rslug)
    if not district or rooms is None:
        raise HTTPException(status_code=404, detail="Страница не найдена")
    data = service.load_hub(db, settings, district=district, rooms=rooms, deal_type=deal_type)
    if data.total == 0:
        raise HTTPException(status_code=404, detail="Нет активных объявлений")
    return _render_hub(request, db, settings, data)


@router.get("/kvartira/{slug}", response_class=HTMLResponse, include_in_schema=False)
def hub_by_slug(slug: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _slug_hub(slug, request, db, "sale")


@router.get("/kvartira/{dslug}/{rslug}", response_class=HTMLResponse, include_in_schema=False)
def hub_district_rooms(
    dslug: str, rslug: str, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    return _district_rooms_hub(dslug, rslug, request, db, "sale")


@router.get("/arenda/{slug}", response_class=HTMLResponse, include_in_schema=False)
def rent_hub_by_slug(slug: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _slug_hub(slug, request, db, "rent")


@router.get("/arenda/{dslug}/{rslug}", response_class=HTMLResponse, include_in_schema=False)
def rent_hub_district_rooms(
    dslug: str, rslug: str, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    return _district_rooms_hub(dslug, rslug, request, db, "rent")


# --- ЖК-страницы /jk ---------------------------------------------------------

def _complex_stats(ch: ComplexHub) -> list[dict]:
    return [
        {"value": fmt_num(ch.total), "label": "объявлений"},
        {"value": fmt_usd(ch.min_price_usd), "label": "цена от"},
        {"value": fmt_usd(ch.median_price_usd), "label": "медиана"},
        {"value": f"{fmt_num(ch.median_ppm_usd)} $/м²", "label": "медиана $/м²"},
    ]


def _complex_intro(ch: ComplexHub) -> str:
    place = f" в {district_locative(ch.district)}" if ch.district else ""
    below = sum(1 for c in ch.cards if c.get("discount_percent"))
    below_txt = f" {below} предложений ниже медианы комплекса." if below else ""
    return (
        f"В ЖК «{ch.name}»{place} сейчас {ch.total} квартир в продаже. "
        f"Цены от {fmt_usd(ch.min_price_usd)}, медиана {fmt_usd(ch.median_price_usd)} "
        f"({fmt_num(ch.median_ppm_usd)} $/м²).{below_txt}"
    )


def _complex_faq(ch: ComplexHub) -> list[dict]:
    return [
        {"q": f"Сколько стоит квартира в ЖК «{ch.name}»?",
         "a": f"Цены от {fmt_usd(ch.min_price_usd)}, медиана {fmt_usd(ch.median_price_usd)} "
              f"({fmt_num(ch.median_ppm_usd)} $/м²) по {ch.total} объявлениям."},
        {"q": "Сколько объявлений в этом ЖК?",
         "a": f"Сейчас {ch.total} активных объявлений с OLX, Uybor и Realt24, обновляется ежедневно."},
        {"q": "Как найти вариант ниже рынка?",
         "a": "Объявления отсортированы по скидке к оценке: самые выгодные сверху, бейдж «−X% к рынку»."},
    ]


def _complex_meta(ch: ComplexHub) -> tuple[str, str, str]:
    place = f" в {district_locative(ch.district)}" if ch.district else " в Ташкенте"
    h1 = f"ЖК «{ch.name}» — квартиры и цены"
    title = f"ЖК {ch.name}{place} — {ch.total} объявлений от {fmt_usd(ch.min_price_usd)} | uyradar.uz"
    desc = (
        f"Квартиры в ЖК «{ch.name}»{place}: {ch.total} объявлений, цены от "
        f"{fmt_usd(ch.min_price_usd)}, медиана {fmt_usd(ch.median_price_usd)} "
        f"({fmt_num(ch.median_ppm_usd)} $/м²). OLX, Uybor и Realt24 с оценкой ниже рынка."
    )
    return h1, title, desc


def _complex_breadcrumbs(ch: ComplexHub) -> list[dict]:
    return [
        {"name": "Главная", "url": "/"},
        {"name": "Жилые комплексы", "url": "/jk"},
        {"name": ch.name, "url": f"/jk/{complex_slug(ch.id, ch.name)}"},
    ]


@router.get("/jk", response_class=HTMLResponse, include_in_schema=False)
def complex_catalog(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    stats = list_complex_stats(db, settings, deal_type="sale")
    complexes = [
        {
            "name": s.name,
            "district": s.district,
            "count": s.count,
            "min_price_usd": s.min_price_usd,
            "median_price_usd": s.median_price_usd,
            "url": f"/jk/{complex_slug(s.id, s.name)}",
        }
        for s in stats
    ]
    context = {
        "h1": "Жилые комплексы Ташкента — цены",
        "page_title": "Жилые комплексы Ташкента — цены на квартиры | uyradar.uz",
        "meta_description": (
            "Каталог жилых комплексов Ташкента: медианные цены, количество объявлений, "
            "квартиры ниже рынка. Данные с OLX, Uybor и Realt24."
        ),
        "canonical": _canonical(request),
        "complexes": complexes,
        "jsonld": _breadcrumb_jsonld(
            request, [{"name": "Главная", "url": "/"}, {"name": "Жилые комплексы", "url": "/jk"}]
        ),
        "jsonld_extra": [],
        "og_image": f"{BASE_URL}/static/logo.png",
    }
    return templates.TemplateResponse(request, "complex_catalog.html", context)


@router.get("/jk/{slug}", response_class=HTMLResponse, include_in_schema=False)
def complex_page(slug: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    rc_id = complex_id_from_slug(slug)
    if rc_id is None:
        raise HTTPException(status_code=404, detail="Страница не найдена")
    settings = get_settings()
    ch = service.load_complex(db, settings, rc_id, deal_type="sale")
    if ch is None:
        raise HTTPException(status_code=404, detail="ЖК не найден или нет активных объявлений")
    h1, title, desc = _complex_meta(ch)
    crumbs = _complex_breadcrumbs(ch)
    faq = _complex_faq(ch)
    jsonld_extra = [j for j in (_itemlist_jsonld(ch), _faq_jsonld(faq)) if j]
    context = {
        "page_title": title,
        "meta_description": desc,
        "canonical": _canonical(request),
        "h1": h1,
        "data": ch,
        "stats": _complex_stats(ch),
        "intro": _complex_intro(ch),
        "faq": faq,
        "breadcrumbs": crumbs,
        "jsonld": _breadcrumb_jsonld(request, crumbs),
        "jsonld_extra": jsonld_extra,
        "og_image": f"{BASE_URL}/static/logo.png",
    }
    return templates.TemplateResponse(request, "complex.html", context)


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(db: Session = Depends(get_db)) -> Response:
    xml = service.build_sitemap_xml(db, get_settings())
    return Response(content=xml, media_type="application/xml")
