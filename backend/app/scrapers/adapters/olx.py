from __future__ import annotations

import json
import re
import time
from typing import Iterator
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from app.scrapers.adapters.common import parse_fixture_cards
from app.scrapers.base import RawListing, SourceAdapter, SourcePageStats
from app.services.normalization import compact_text, normalize_district


class OlxAdapter(SourceAdapter):
    source = "olx"
    fixture_name = "olx.html"
    supports_live = True
    page_size = 40
    search_url = "https://www.olx.uz/nedvizhimost/kvartiry/prodazha/tashkent/"

    def parse(self, html: str) -> list[RawListing]:
        return parse_fixture_cards(html, self.source)

    def fetch_live(self, max_pages: int = 1, delay_seconds: float = 2.0) -> list[RawListing]:
        listings: list[RawListing] = []
        for page_listings in self.fetch_live_pages(max_pages=max_pages, delay_seconds=delay_seconds):
            listings.extend(page_listings)
        return _unique_by_source_id(listings)

    def fetch_live_pages(self, max_pages: int | None = 1, delay_seconds: float = 2.0) -> Iterator[list[RawListing]]:
        page_limit = max(1, max_pages) if max_pages is not None else None
        last_page = page_limit
        with httpx.Client(
            timeout=25,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TashkentValueFlats/0.1; +https://github.com/Asekesh/tashkent-value-flats)",
                "Accept-Language": "ru,en;q=0.8",
            },
        ) as client:
            page = 1
            while True:
                url = _page_url(self.search_url, page)
                response = client.get(url)
                response.raise_for_status()
                if page == 1 and page_limit is None:
                    last_page = _extract_total_pages(response.text)
                yield self.parse_live_page(response.text)
                if last_page is not None and page >= last_page:
                    break
                page += 1
                time.sleep(delay_seconds)

    def count_live_pages(self) -> SourcePageStats:
        with httpx.Client(
            timeout=25,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TashkentValueFlats/0.1; +https://github.com/Asekesh/tashkent-value-flats)",
                "Accept-Language": "ru,en;q=0.8",
            },
        ) as client:
            response = client.get(self.search_url)
            response.raise_for_status()
        total_pages = _extract_total_pages(response.text)
        return SourcePageStats(source=self.source, total_pages=total_pages, page_size=self.page_size)

    def parse_live_page(self, html: str) -> list[RawListing]:
        soup = BeautifulSoup(html, "html.parser")
        photo_map = _extract_prerendered_photos(html)
        listings: list[RawListing] = []
        seen: set[str] = set()
        for offer in _extract_jsonld_offers(soup):
            raw = _offer_to_raw_listing(offer)
            if raw and raw.source_id not in seen:
                listings.append(raw)
                seen.add(raw.source_id)
        for card in soup.select("[data-cy=l-card]"):
            raw = _card_to_raw_listing(card)
            if raw and raw.source_id not in seen:
                listings.append(raw)
                seen.add(raw.source_id)
        for raw in listings:
            if not raw.photos:
                raw.photos = photo_map.get(raw.source_id) or photo_map.get(
                    _source_id_from_url(raw.url)
                ) or []
        return listings

    def fetch_listing_photos(self, url: str, client: httpx.Client) -> list[str] | None:
        """Fetch one listing's detail page and return its photos.

        Returns ``None`` when the listing is gone (HTTP 404) so the caller can
        delist it; an empty list means the page loaded but exposed no photos.
        """
        response = client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _extract_detail_photos(response.text)


_PRERENDERED_STATE_RE = re.compile(
    r"window\.__PRERENDERED_STATE__\s*=\s*(\"(?:[^\"\\]|\\.)*\")"
)


def _load_prerendered_state(html: str) -> dict | None:
    """Decode OLX's ``window.__PRERENDERED_STATE__`` blob — a JSON string
    literal that itself holds escaped JSON."""
    match = _PRERENDERED_STATE_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(json.loads(match.group(1)))
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _extract_prerendered_photos(html: str) -> dict[str, list[str]]:
    """Photos by id/url-code from OLX's ``window.__PRERENDERED_STATE__`` blob.

    Card thumbnails on pages past the first are server-rendered as a
    ``no_thumbnail`` placeholder and only hydrated client-side, so the photos
    have to come from the embedded state instead.
    """
    data = _load_prerendered_state(html)
    if data is None:
        return {}
    ads = data.get("listing", {}).get("listing", {}).get("ads")
    if not isinstance(ads, list):
        return {}
    photo_map: dict[str, list[str]] = {}
    for ad in ads:
        if not isinstance(ad, dict):
            continue
        photos = [str(p) for p in ad.get("photos") or [] if p][:5]
        if not photos:
            continue
        if ad.get("id") is not None:
            photo_map[str(ad["id"])] = photos
        url = compact_text(ad.get("url"))
        if url:
            photo_map[_source_id_from_url(url)] = photos
    return photo_map


def _extract_detail_photos(html: str) -> list[str]:
    """Photos from a single listing's detail page (``ad.ad.photos`` in the
    ``__PRERENDERED_STATE__`` blob). Used to backfill listings that dropped out
    of the 25-page search window and can't be reached via the listing pages."""
    data = _load_prerendered_state(html)
    if data is None:
        return []
    ad = data.get("ad")
    if isinstance(ad, dict):
        ad = ad.get("ad", ad)
    photos = ad.get("photos") if isinstance(ad, dict) else None
    if isinstance(photos, list):
        return [str(photo) for photo in photos if photo][:5]
    return []


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


_OLX_BASE = "https://www.olx.uz"
_CURRENCY_MAP = {
    "сум": "UZS",
    "сўм": "UZS",
    "soʻm": "UZS",
    "som": "UZS",
    "uzs": "UZS",
    "$": "USD",
    "usd": "USD",
    "у.е.": "USD",
    "у. е.": "USD",
    "€": "EUR",
    "eur": "EUR",
}


def _card_to_raw_listing(card) -> RawListing | None:
    title_el = card.select_one('[data-cy="ad-card-title"] h4, [data-testid="ad-card-title"] h4, h4, h6')
    link_el = card.select_one('a[href]')
    price_el = card.select_one('[data-testid="ad-price"], [data-testid="ad-price-text"]')
    location_el = card.select_one('[data-testid="location-date"]')
    if not title_el or not link_el or not price_el:
        return None
    title = compact_text(title_el.get_text(" "))
    href = link_el.get("href") or ""
    if not href:
        return None
    url = href if href.startswith("http") else _OLX_BASE + href
    price_value, currency = _parse_price(price_el.get_text(" "))
    if price_value is None:
        return None
    area_m2 = _extract_area(title)
    rooms = _extract_rooms(title)
    if not area_m2 or not rooms:
        return None
    floor, total_floors = _extract_floor(title)
    location_text = compact_text(location_el.get_text(" ")) if location_el else ""
    district = normalize_district(_district_from_location(location_text))
    source_id = card.get("id") or _source_id_from_url(url)
    photo_el = card.select_one("img")
    photos: list[str] = []
    if photo_el:
        src = photo_el.get("src") or ""
        if src and "no_thumbnail" not in src:
            photos.append(src)
    return RawListing(
        source="olx",
        source_id=str(source_id),
        url=url,
        title=title,
        price=price_value,
        currency=currency,
        area_m2=area_m2,
        rooms=rooms,
        floor=floor,
        total_floors=total_floors,
        district=district,
        address_raw=_address_from_title(title, district),
        description=title,
        photos=photos,
        seller_type=None,
    )


def _parse_price(text: str) -> tuple[float | None, str]:
    text = compact_text(text)
    if not text:
        return None, "UZS"
    lowered = text.lower()
    currency = "UZS"
    for marker, code in _CURRENCY_MAP.items():
        if marker in lowered:
            currency = code
            break
    digits = re.sub(r"[^0-9]", "", text)
    if not digits:
        return None, currency
    try:
        return float(digits), currency
    except ValueError:
        return None, currency


def _district_from_location(location_text: str) -> str:
    if not location_text:
        return ""
    parts = [chunk.strip() for chunk in re.split(r"[—-]", location_text) if chunk.strip()]
    locality = parts[0] if parts else location_text
    chunks = [chunk.strip() for chunk in locality.split(",") if chunk.strip()]
    if not chunks:
        return locality
    for chunk in chunks:
        if "район" in chunk.lower() or "tuman" in chunk.lower():
            return chunk
    return chunks[-1]


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


def _page_url(search_url: str, page: int) -> str:
    return search_url if page == 1 else f"{search_url}?page={page}"


def _extract_total_pages(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    pages = [1]
    for link in soup.select("a[href]"):
        text = compact_text(link.get_text(" "))
        if text.isdigit():
            pages.append(int(text))
        href = link.get("href") or ""
        query_pages = parse_qs(urlparse(href).query).get("page")
        for value in query_pages or []:
            if value.isdigit():
                pages.append(int(value))
    return max(pages)
