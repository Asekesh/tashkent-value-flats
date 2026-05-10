from __future__ import annotations

from bs4 import BeautifulSoup

from app.scrapers.base import RawListing
from app.services.normalization import (
    compact_text,
    normalize_currency,
    normalize_district,
    parse_floor,
    parse_number,
)


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
