from __future__ import annotations

from math import ceil
import re
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
    unique_by_source_id,
)
from app.scrapers.base import RawListing, SourceAdapter, SourcePageStats
from app.services.normalization import compact_text, normalize_currency, normalize_district, parse_floor


class Realt24Adapter(SourceAdapter):
    source = "realt24"
    fixture_name = "realt24.html"
    supports_live = True
    page_size = 20
    api_url = "https://api.realt24.uz/api/v1/properties"
    public_url_template = "https://realt24.uz/ru/listing/{source_id}/"

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
            page = 1
            while True:
                payload = self.fetch_api_page(client, page)
                yield self.parse_api_page(payload)
                total_pages = _page_count(payload, len(payload.get("data") or []) or self.page_size)
                if page_limit is not None and page >= page_limit:
                    break
                if page_limit is None and total_pages is not None and page >= total_pages:
                    break
                if total_pages is None and not _has_more(payload):
                    break
                page += 1
                time.sleep(delay_seconds)

    def count_live_pages(self) -> SourcePageStats:
        with httpx.Client(timeout=25, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            payload = self.fetch_api_page(client, 1)
            page_size = _page_size(payload) or self.page_size
            total_pages = _page_count(payload, page_size)
            total_listings = _total_count(payload)
            if total_pages is None:
                total_pages = 1
                while _has_more(payload):
                    payload = self.fetch_api_page(client, total_pages + 1)
                    total_pages += 1
        return SourcePageStats(
            source=self.source,
            total_pages=total_pages,
            page_size=page_size,
            total_listings=total_listings,
        )

    def fetch_api_page(self, client: httpx.Client, page: int) -> dict[str, Any]:
        response = client.get(
            self.api_url,
            params={
                "addressRouteKey": "tashkentcity",
                "addressTypeKey": "region",
                "categoryIds": "1",
                "categoryType": "sale",
                "subCategoryIds": "4,6",
                "page": page,
            },
        )
        response.raise_for_status()
        return response.json()

    def parse_api_page(self, payload: dict[str, Any]) -> list[RawListing]:
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        return [
            listing
            for item in items
            if isinstance(item, dict)
            for listing in [self.api_item_to_listing(item)]
            if listing is not None
        ]

    def api_item_to_listing(self, item: dict[str, Any]) -> RawListing | None:
        attrs = item.get("attributes")
        if not isinstance(attrs, dict) or attrs.get("statusKey") not in (None, "active"):
            return None
        source_id = compact_text(str(item.get("id") or ""))
        title = localized_text(attrs.get("name")) or localized_text(attrs.get("secondaryName"))
        rooms = _extract_rooms(title)
        area_m2 = _extract_area(title)
        floor, total_floors = parse_floor(title)
        price, currency = _price_and_currency(attrs)
        if not source_id or not title or price is None or not area_m2 or not rooms:
            return None
        address = _address_text(item)
        district = normalize_district(address)
        photos = _photo_urls(attrs.get("imageSets"))
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
            address_raw=address or district,
            description=localized_text(attrs.get("description")) or title,
            photos=photos,
            seller_type=_seller_type(item),
            published_at=parse_iso_datetime(attrs.get("publishedAt") or attrs.get("createdAt")),
        )


def _price_and_currency(attrs: dict[str, Any]) -> tuple[float | None, str]:
    currency = normalize_currency(attrs.get("currency"))
    prices = attrs.get("price")
    if isinstance(prices, dict):
        price = to_float(prices.get(currency.lower())) or to_float(prices.get("usd")) or to_float(next(iter(prices.values()), None))
        return price, currency
    return to_float(prices), currency


def _extract_rooms(title: str) -> int | None:
    match = re.search(r"(\d+)\s*[- ]?комн", title, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"\b([1-8])\s*xon", title, flags=re.IGNORECASE)
    if not match:
        return None
    rooms = int(match.group(1))
    return rooms if 1 <= rooms <= 8 else None


def _extract_area(title: str) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:м2|м²|m²)", title, flags=re.IGNORECASE)
    if not match:
        return None
    area = float(match.group(1).replace(",", "."))
    return area if 10 <= area <= 500 else None


def _address_text(item: dict[str, Any]) -> str:
    address = (
        item.get("relations", {})
        .get("address", {})
        .get("data", {})
        .get("attributes", {})
        .get("fullAddress")
    )
    return localized_text(address)


def _photo_urls(image_sets: Any) -> list[str]:
    if not isinstance(image_sets, list):
        return []
    photos: list[str] = []
    for image_set in image_sets:
        if not isinstance(image_set, dict):
            continue
        url = compact_text(image_set.get("w600") or image_set.get("w450") or image_set.get("original"))
        if url:
            photos.append(url)
    return photos[:8]


def _seller_type(item: dict[str, Any]) -> str | None:
    role = (
        item.get("relations", {})
        .get("user", {})
        .get("data", {})
        .get("relations", {})
        .get("role", {})
        .get("data", {})
        .get("attributes", {})
        .get("key")
    )
    return compact_text(role) or None


def _has_more(payload: dict[str, Any]) -> bool:
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("hasNext"))


def _page_count(payload: dict[str, Any], page_size: int) -> int | None:
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return None
    for key in ("pageCount", "totalPages", "lastPage", "total_pages", "totalPage"):
        value = meta.get(key)
        if isinstance(value, int) and value > 0:
            return value
    total = _total_count(payload)
    if total is None or page_size <= 0:
        return None
    return max(1, ceil(total / page_size))


def _page_size(payload: dict[str, Any]) -> int | None:
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if isinstance(meta, dict):
        for key in ("perPage", "pageSize", "limit", "per_page"):
            value = meta.get(key)
            if isinstance(value, int) and value > 0:
                return value
    items = payload.get("data") if isinstance(payload, dict) else None
    return len(items) if isinstance(items, list) and items else None


def _total_count(payload: dict[str, Any]) -> int | None:
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return None
    for key in ("total", "totalCount", "total_count", "count"):
        value = meta.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return None
