from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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


class SourceAdapter:
    source: str
    fixture_name: str

    def parse(self, html: str) -> list[RawListing]:
        raise NotImplementedError
