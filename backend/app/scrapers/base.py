from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator


@dataclass
class RawListing:
    source: str
    source_id: str
    url: str
    title: str
    price: float
    currency: str
    area_m2: float
    rooms: int
    district: str
    address_raw: str
    floor: int | None = None
    total_floors: int | None = None
    description: str | None = None
    photos: list[str] = field(default_factory=list)
    seller_type: str | None = None
    published_at: datetime | None = None


@dataclass
class SourcePageStats:
    source: str
    total_pages: int | None = None
    page_size: int | None = None
    total_listings: int | None = None


class SourceAdapter:
    source: str
    fixture_name: str
    supports_live: bool = False
    page_size: int | None = None

    def parse(self, html: str) -> list[RawListing]:
        raise NotImplementedError

    def fetch_live(self, max_pages: int = 1, delay_seconds: float = 2.0) -> list[RawListing]:
        raise NotImplementedError(f"{self.source} live scraping is not implemented")

    def fetch_live_pages(self, max_pages: int | None = 1, delay_seconds: float = 2.0) -> Iterator[list[RawListing]]:
        yield self.fetch_live(max_pages=max_pages or 1, delay_seconds=delay_seconds)

    def count_live_pages(self) -> SourcePageStats:
        return SourcePageStats(source=self.source, page_size=self.page_size)
