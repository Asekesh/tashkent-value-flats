from __future__ import annotations

from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from app.scrapers.base import RawListing
from app.services.normalization import (
    compact_text,
    normalize_currency,
    normalize_district,
    parse_floor,
    parse_number,
)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TashkentValueFlats/0.1; +https://github.com/Asekesh/tashkent-value-flats)",
    "Accept-Language": "ru,en;q=0.8",
}


def parse_fixture_cards(html: str, source: str) -> list[RawListing]:
    soup = BeautifulSoup(html, "html.parser")
    listings: list[RawListing] = []
    for card in soup.select("[data-listing]"):
        price_text = compact_text(card.select_one("[data-price]").get_text(" ") if card.select_one("[data-price]") else "")
        area = parse_number(card.get("data-area") or text_for(card, "[data-area]"))
        rooms = parse_number(card.get("data-rooms") or text_for(card, "[data-rooms]"))
        price = parse_number(card.get("data-price") or price_text)
        if not area or not rooms or not price:
            continue
        currency = normalize_currency(card.get("data-currency") or price_text)
        floor, total_floors = parse_floor(card.get("data-floor") or text_for(card, "[data-floor]"))
        listings.append(
            RawListing(
                source=source,
                source_id=card.get("data-id") or text_for(card, "[data-id]") or f"{source}-{len(listings) + 1}",
                url=card.get("data-url") or text_for(card, "a") or "#",
                title=text_for(card, "[data-title]") or text_for(card, "h2") or "Без названия",
                price=float(price),
                currency=currency,
                area_m2=float(area),
                rooms=int(rooms),
                floor=floor,
                total_floors=total_floors,
                district=normalize_district(card.get("data-district") or text_for(card, "[data-district]")),
                address_raw=card.get("data-address") or text_for(card, "[data-address]"),
                description=text_for(card, "[data-description]") or None,
                photos=[img.get("src") for img in card.select("img[src]")],
                seller_type=card.get("data-seller") or text_for(card, "[data-seller]") or None,
            )
        )
    return listings


def text_for(card, selector: str) -> str:
    element = card.select_one(selector)
    if not element:
        return ""
    if selector == "a" and element.get("href"):
        return element.get("href")
    return compact_text(element.get_text(" "))


def localized_text(value: Any, locale: str = "ru") -> str:
    if isinstance(value, dict):
        return compact_text(value.get(locale) or value.get("ru") or value.get("uz") or value.get("en") or "")
    return compact_text(str(value or ""))


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    number = parse_number(value)
    return int(number) if number is not None else None


def to_float(value: Any) -> float | None:
    number = parse_number(value)
    return float(number) if number is not None else None


def unique_by_source_id(listings: list[RawListing]) -> list[RawListing]:
    seen: set[str] = set()
    unique: list[RawListing] = []
    for listing in listings:
        if listing.source_id in seen:
            continue
        seen.add(listing.source_id)
        unique.append(listing)
    return unique
