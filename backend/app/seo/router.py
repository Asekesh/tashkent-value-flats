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
from app.seo.service import BASE_URL, HubData, fmt_num, fmt_usd
from app.seo.slugs import (
    DISTRICT_SLUGS,
    district_from_slug,
    district_locative,
    rooms_from_slug,
    rooms_label,
    rooms_slug,
)

router = APIRouter(tags=["seo"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["usd"] = fmt_usd
templates.env.filters["num"] = fmt_num


def _canonical(request: Request) -> str:
    return BASE_URL + request.url.path


def _breadcrumbs(data: HubData) -> list[dict]:
    crumbs = [{"name": "Главная", "url": "/"}, {"name": "Квартиры", "url": "/kvartira"}]
    if data.district:
        crumbs.append({"name": data.district, "url": f"/kvartira/{DISTRICT_SLUGS[data.district]}"})
        if data.rooms:
            crumbs.append(
                {
                    "name": rooms_label(data.rooms),
                    "url": f"/kvartira/{DISTRICT_SLUGS[data.district]}/{rooms_slug(data.rooms)}",
                }
            )
    elif data.rooms:
        crumbs.append({"name": rooms_label(data.rooms), "url": f"/kvartira/{rooms_slug(data.rooms)}"})
    return crumbs


def _related(db: Session, settings, data: HubData) -> list[dict]:
    """Блоки перелинковки — только реально существующие срезы."""
    districts, rooms, combos = service.available_hubs(db, settings)
    sections: list[dict] = []

    if data.district and not data.rooms:
        # район → его комнатность + другие районы
        links = [
            {"label": f"{rooms_label(rm)} в этом районе", "url": f"/kvartira/{DISTRICT_SLUGS[data.district]}/{rooms_slug(rm)}"}
            for (dist, rm) in sorted(combos) if dist == data.district
        ]
        if links:
            sections.append({"title": "По комнатности", "links": links})
        sections.append({"title": "Другие районы", "links": _district_links(districts, exclude=data.district)})
    elif data.rooms and not data.district:
        # комнатность по городу → та же комнатность по районам + другая комнатность
        links = [
            {"label": dist, "url": f"/kvartira/{DISTRICT_SLUGS[dist]}/{rooms_slug(data.rooms)}"}
            for (dist, rm) in sorted(combos) if rm == data.rooms
        ]
        if links:
            sections.append({"title": f"{rooms_label(data.rooms)} по районам", "links": links})
        sections.append({"title": "Другая комнатность", "links": _room_links(rooms, exclude=data.rooms)})
    elif data.district and data.rooms:
        # район+комнатность → другая комнатность здесь + этот же тип в других районах
        other_rooms = [
            {"label": rooms_label(rm), "url": f"/kvartira/{DISTRICT_SLUGS[data.district]}/{rooms_slug(rm)}"}
            for (dist, rm) in sorted(combos) if dist == data.district and rm != data.rooms
        ]
        if other_rooms:
            sections.append({"title": f"Другая комнатность в {district_locative(data.district)}", "links": other_rooms})
        other_dist = [
            {"label": dist, "url": f"/kvartira/{DISTRICT_SLUGS[dist]}/{rooms_slug(data.rooms)}"}
            for (dist, rm) in sorted(combos) if rm == data.rooms and dist != data.district
        ]
        if other_dist:
            sections.append({"title": f"{rooms_label(data.rooms)} в других районах", "links": other_dist})
    return sections


def _district_links(districts: dict[str, int], exclude: str | None = None) -> list[dict]:
    return [
        {"label": dist, "url": f"/kvartira/{DISTRICT_SLUGS[dist]}"}
        for dist in sorted(districts) if dist != exclude
    ]


def _room_links(rooms: dict[int, int], exclude: int | None = None) -> list[dict]:
    return [
        {"label": rooms_label(rm), "url": f"/kvartira/{rooms_slug(rm)}"}
        for rm in sorted(rooms) if rm != exclude
    ]


def _meta(data: HubData) -> tuple[str, str, str]:
    """(h1, title, meta_description) для трёх видов хаба."""
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


def _render_hub(request: Request, db: Session, settings, data: HubData) -> HTMLResponse:
    h1, title, desc = _meta(data)
    crumbs = _breadcrumbs(data)
    context = {
        "page_title": title,
        "meta_description": desc,
        "canonical": _canonical(request),
        "h1": h1,
        "data": data,
        "breadcrumbs": crumbs,
        "related": _related(db, settings, data),
        "jsonld": _breadcrumb_jsonld(request, crumbs),
        "og_image": f"{BASE_URL}/static/logo.png",
    }
    return templates.TemplateResponse(request, "hub.html", context)


@router.get("/kvartira", response_class=HTMLResponse, include_in_schema=False)
def catalog(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    districts, rooms, _ = service.available_hubs(db, settings)
    context = {
        "page_title": "Квартиры в Ташкенте по районам — каталог | uyradar.uz",
        "meta_description": (
            "Каталог квартир в Ташкенте по районам и комнатности: Чиланзар, Юнусабад, "
            "Мирабад и другие. Объявления с OLX, Uybor и Realt24 с оценкой ниже рынка."
        ),
        "canonical": _canonical(request),
        "district_links": _district_links(districts),
        "room_links": _room_links(rooms),
        "jsonld": _breadcrumb_jsonld(
            request, [{"name": "Главная", "url": "/"}, {"name": "Квартиры", "url": "/kvartira"}]
        ),
        "og_image": f"{BASE_URL}/static/logo.png",
    }
    return templates.TemplateResponse(request, "catalog.html", context)


@router.get("/kvartira/{slug}", response_class=HTMLResponse, include_in_schema=False)
def hub_by_slug(slug: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    rooms = rooms_from_slug(slug)
    if rooms is not None:
        data = service.load_hub(db, settings, rooms=rooms)
    else:
        district = district_from_slug(slug)
        if not district:
            raise HTTPException(status_code=404, detail="Страница не найдена")
        data = service.load_hub(db, settings, district=district)
    if data.total == 0:
        raise HTTPException(status_code=404, detail="Нет активных объявлений")
    return _render_hub(request, db, settings, data)


@router.get("/kvartira/{dslug}/{rslug}", response_class=HTMLResponse, include_in_schema=False)
def hub_district_rooms(
    dslug: str, rslug: str, request: Request, db: Session = Depends(get_db)
) -> HTMLResponse:
    settings = get_settings()
    district = district_from_slug(dslug)
    rooms = rooms_from_slug(rslug)
    if not district or rooms is None:
        raise HTTPException(status_code=404, detail="Страница не найдена")
    data = service.load_hub(db, settings, district=district, rooms=rooms)
    if data.total == 0:
        raise HTTPException(status_code=404, detail="Нет активных объявлений")
    return _render_hub(request, db, settings, data)


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(db: Session = Depends(get_db)) -> Response:
    xml = service.build_sitemap_xml(db, get_settings())
    return Response(content=xml, media_type="application/xml")
