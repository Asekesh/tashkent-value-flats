from __future__ import annotations

from math import ceil
import time
from typing import Any
from typing import Iterator

import httpx

from app.scrapers.adapters.common import (
    DEFAULT_HEADERS,
    localized_text,
    parse_fixture_cards,
    parse_iso_datetime,
    to_float,
    to_int,
    unique_by_source_id,
)
from app.scrapers.base import RawListing, SourceAdapter, SourcePageStats
from app.services.normalization import compact_text, normalize_currency, normalize_district


class UyborAdapter(SourceAdapter):
    source = "uybor"
    fixture_name = "uybor.html"
    supports_live = True
    page_size = 50
    api_url = "https://api.uybor.uz/api/v1/listings"
    locations_url = "https://api.uybor.uz/api/v1/listings/locations"
    public_url_template = "https://uybor.uz/listings/{source_id}"

    def parse(self, html: str) -> list[RawListing]:
        return parse_fixture_cards(html, self.source)

    def fetch_live(self, max_pages: int = 1, delay_seconds: float = 2.0) -> list[RawListing]:
        listings: list[RawListing] = []
        for page_listings in self.fetch_live_pages(max_pages=max_pages, delay_seconds=delay_seconds):
            listings.extend(page_listings)
        return unique_by_source_id(listings)

    def fetch_live_pages(self, max_pages: int | None = 1, delay_seconds: float = 2.0) -> Iterator[list[RawListing]]:
        page_limit = max(1, max_pages) if max_pages is not None else None
        with httpx.Client(timeout=25, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            location_names = self.fetch_location_names(client)
            page = 1
            while True:
                payload = self.fetch_api_page(client, page)
                yield self.parse_api_page(payload, location_names=location_names)
                total_pages = _page_count(payload, self.page_size)
                if page_limit is not None and page >= page_limit:
                    break
                if page_limit is None and total_pages is not None and page >= total_pages:
                    break
                if total_pages is None and not _has_more(payload, page):
                    break
                page += 1
                time.sleep(delay_seconds)

    def count_live_pages(self) -> SourcePageStats:
        with httpx.Client(timeout=25, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            payload = self.fetch_api_page(client, 1)
        total = to_int(payload.get("total")) if isinstance(payload, dict) else None
        return SourcePageStats(
            source=self.source,
            total_pages=_page_count(payload, self.page_size),
            page_size=self.page_size,
            total_listings=total,
        )

    def fetch_api_page(self, client: httpx.Client, page: int) -> dict[str, Any]:
        response = client.get(
            self.api_url,
            params={
                "operationType__eq": "sale",
                "category__eq": 7,
                "region__eq": 13,
                "isActive__eq": "true",
                "moderationStatus__in": "approved",
                "limit": self.page_size,
                "page": page,
            },
        )
        response.raise_for_status()
        return response.json()

    def fetch_location_names(self, client: httpx.Client) -> dict[int, str]:
        try:
            response = client.get(self.locations_url, params={"parentId": 13, "limit": 200})
            response.raise_for_status()
        except httpx.HTTPError:
            return {}
        payload = response.json()
        locations = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(locations, list):
            return {}
        names: dict[int, str] = {}
        for location in locations:
            if not isinstance(location, dict):
                continue
            location_id = to_int(location.get("id"))
            name = localized_text(location.get("name"))
            if location_id and name:
                names[location_id] = name
        return names

    def parse_api_page(self, payload: dict[str, Any], location_names: dict[int, str] | None = None) -> list[RawListing]:
        items = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        return [
            listing
            for item in items
            if isinstance(item, dict)
            for listing in [self.api_item_to_listing(item, location_names or {})]
            if listing is not None
        ]

    def api_item_to_listing(self, item: dict[str, Any], location_names: dict[int, str]) -> RawListing | None:
        if item.get("isActive") is False or item.get("moderationStatus") not in (None, "approved"):
            return None
        source_id = compact_text(str(item.get("id") or ""))
        area_m2 = to_float(item.get("square"))
        rooms = _rooms_from_value(item.get("room"))
        currency = normalize_currency(item.get("priceCurrency"))
        price = _total_price(item, currency, area_m2)
        if not source_id or price is None or area_m2 is None or rooms is None:
            return None
        district_id = to_int(item.get("districtId"))
        district = normalize_district(location_names.get(district_id or 0) or _district_from_text(item))
        address = compact_text(item.get("address")) or district
        floor = to_int(item.get("floor"))
        total_floors = to_int(item.get("floorTotal"))
        description = compact_text(item.get("description"))
        photos = [
            compact_text(photo.get("url"))
            for photo in item.get("media", [])
            if isinstance(photo, dict) and compact_text(photo.get("url"))
        ][:8]
        title = _title_for(item, rooms, area_m2, floor, total_floors)
        return RawListing(
            source=self.source,
            source_id=source_id,
            url=self.public_url_template.format(source_id=source_id),
            title=title,
            price=price,
            currency=currency,
            area_m2=area_m2,
            rooms=rooms,
            floor=floor,
            total_floors=total_floors,
            district=district,
            address_raw=address,
            description=description or title,
            photos=photos,
            seller_type=None,
            published_at=parse_iso_datetime(item.get("upAt") or item.get("createdAt")),
        )


def _rooms_from_value(value: Any) -> int | None:
    text = compact_text(str(value or "")).lower()
    if text in {"studio", "free_layout", "freelayout"}:
        return 1
    rooms = to_int(text)
    if rooms is not None and 1 <= rooms <= 8:
        return rooms
    if "more" in text:
        return 5
    return None


def _total_price(item: dict[str, Any], currency: str, area_m2: float | None) -> float | None:
    prices = item.get("prices")
    if isinstance(prices, dict):
        price = to_float(prices.get(currency.lower()))
        if price is not None:
            return price
        price = to_float(prices.get("usd")) or to_float(prices.get("uzs"))
        if price is not None:
            return price

    price = to_float(item.get("price"))
    if item.get("priceType") == "sqm" and price is not None and area_m2:
        return round(price * area_m2, 2)
    return price


def _district_from_text(item: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [compact_text(item.get("address")), compact_text(item.get("description"))]
        if part
    )


def _title_for(item: dict[str, Any], rooms: int, area_m2: float, floor: int | None, total_floors: int | None) -> str:
    title = f"{rooms}-комнатная квартира - {area_m2:g} м2"
    if floor and total_floors:
        title = f"{title}, {floor}/{total_floors} этаж"
    address = compact_text(item.get("address"))
    return f"{title}, {address}" if address else title


def _has_more(payload: dict[str, Any], current_page: int) -> bool:
    total = to_int(payload.get("total"))
    results = payload.get("results")
    if total is None or not isinstance(results, list) or not results:
        return False
    return current_page * len(results) < total


def _page_count(payload: dict[str, Any], page_size: int) -> int | None:
    total = to_int(payload.get("total")) if isinstance(payload, dict) else None
    if total is None:
        return None
    return max(1, ceil(total / page_size))
