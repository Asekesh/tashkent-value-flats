from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.scrapers.adapters.common import parse_fixture_cards
from app.scrapers.base import RawListing, SourceAdapter
from app.services.normalization import compact_text, normalize_district


class OlxAdapter(SourceAdapter):
    source = "olx"
    fixture_name = "olx.html"
    supports_live = True
    search_url = "https://www.olx.uz/nedvizhimost/kvartiry/prodazha/tashkent/"

    def parse(self, html: str) -> list[RawListing]:
        return parse_fixture_cards(html, self.source)

    def fetch_live(self, max_pages: int = 1, delay_seconds: float = 2.0) -> list[RawListing]:
        listings: list[RawListing] = []
        with httpx.Client(
            timeout=25,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TashkentValueFlats/0.1; +https://github.com/Asekesh/tashkent-value-flats)",
                "Accept-Language": "ru,en;q=0.8",
            },
        ) as client:
            for page in range(1, max(1, max_pages) + 1):
                url = self.search_url if page == 1 else f"{self.search_url}?page={page}"
                response = client.get(url)
                response.raise_for_status()
                listings.extend(self.parse_live_page(response.text))
                if page < max_pages:
                    time.sleep(delay_seconds)
        return _unique_by_source_id(listings)

    def parse_live_page(self, html: str) -> list[RawListing]:
        soup = BeautifulSoup(html, "html.parser")
        listings: list[RawListing] = []
        for offer in _extract_jsonld_offers(soup):
            raw = _offer_to_raw_listing(offer)
            if raw:
                listings.append(raw)
        return listings


def _extract_jsonld_offers(soup: BeautifulSoup) -> list[dict]:
    offers: list[dict] = []
    for script in soup.select('script[type="application/ld+json"]'):
        text = script.string or script.get_text()
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            aggregate = data.get("offers")
            nested_offers = aggregate.get("offers") if isinstance(aggregate, dict) else None
            if isinstance(nested_offers, list):
                offers.extend([offer for offer in nested_offers if isinstance(offer, dict)])
    return offers


def _offer_to_raw_listing(offer: dict) -> RawListing | None:
    title = compact_text(offer.get("name"))
    url = compact_text(offer.get("url"))
    price = offer.get("price")
    if not title or not url or not isinstance(price, (int, float)):
        return None
    area_m2 = _extract_area(title)
    rooms = _extract_rooms(title)
    if not area_m2 or not rooms:
        return None
    floor, total_floors = _extract_floor(title)
    district = normalize_district(_extract_area_served(offer))
    source_id = _source_id_from_url(url)
    photos = offer.get("image") if isinstance(offer.get("image"), list) else []
    return RawListing(
        source="olx",
        source_id=source_id,
        url=url,
        title=title,
        price=float(price),
        currency=offer.get("priceCurrency") or "UZS",
        area_m2=area_m2,
        rooms=rooms,
        floor=floor,
        total_floors=total_floors,
        district=district,
        address_raw=_address_from_title(title, district),
        description=title,
        photos=[str(photo) for photo in photos[:5]],
        seller_type=None,
    )


def _extract_area_served(offer: dict) -> str:
    area = offer.get("areaServed")
    if isinstance(area, dict):
        return compact_text(area.get("name"))
    return compact_text(str(area or ""))


def _source_id_from_url(url: str) -> str:
    match = re.search(r"-ID([A-Za-z0-9]+)\.html", url)
    if match:
        return match.group(1)
    path = urlparse(url).path.strip("/")
    return path.rsplit("/", 1)[-1] or url


def _extract_rooms(title: str) -> int | None:
    text = title.lower()
    patterns = [
        r"(\d+)\s*[- ]?х\s*ком",
        r"(\d+)\s*[- ]?комнат",
        r"(\d+)\s*хона",
        r"(\d+)\s*xon",
        r"\b([1-5])\s*/\s*\d+\s*/\s*\d+\b",
        r"\b([1-5])в[2-5]\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            rooms = int(match.group(1))
            if 1 <= rooms <= 8:
                return rooms
    return None


def _extract_floor(title: str) -> tuple[int | None, int | None]:
    match = re.search(r"\b\d+\s*/\s*(\d+)\s*/\s*(\d+)\b", title)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def _extract_area(title: str) -> float | None:
    patterns = [
        r"(\d+(?:[.,]\d+)?)\s*(?:м2|м²|кв\.?\s*м|квадрат)",
        r"(?:квадрат|квадратов|кв\.?\s*м)\s*(\d+(?:[.,]\d+)?)",
        r"\b\d+\s*/\s*\d+\s*/\s*\d+\s+(\d+(?:[.,]\d+)?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if match:
            area = float(match.group(1).replace(",", "."))
            if 10 <= area <= 500:
                return area
    return None


def _address_from_title(title: str, district: str) -> str:
    cleaned = re.sub(r"\b\d+\s*/\s*\d+\s*/\s*\d+\b", " ", title)
    cleaned = re.sub(r"\d+(?:[.,]\d+)?\s*(?:м2|м²|кв\.?\s*м|квадрат)", " ", cleaned, flags=re.IGNORECASE)
    cleaned = compact_text(cleaned)
    return cleaned[:180] or district


def _unique_by_source_id(listings: list[RawListing]) -> list[RawListing]:
    seen: set[str] = set()
    unique: list[RawListing] = []
    for listing in listings:
        if listing.source_id in seen:
            continue
        seen.add(listing.source_id)
        unique.append(listing)
    return unique
