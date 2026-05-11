from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MarketEstimate(BaseModel):
    market_price_per_m2_usd: Optional[float]
    sample_size: int
    basis: str
    confidence: str
    discount_percent: Optional[float] = None
    is_below_market: bool = False


class ListingOut(BaseModel):
    id: int
    source: str
    source_id: str
    url: str
    title: str
    price: float
    currency: str
    price_usd: float
    area_m2: float
    price_per_m2_usd: float
    rooms: int
    floor: Optional[int]
    total_floors: Optional[int]
    district: str
    address_raw: str
    building_key: Optional[str]
    description: Optional[str]
    photos: list[str]
    seller_type: Optional[str]
    published_at: Optional[datetime]
    seen_at: datetime
    status: str
    duplicate_count: int
    source_urls: list[dict[str, str]]
    market: Optional[MarketEstimate] = None

    model_config = ConfigDict(from_attributes=True)


class ListingsPage(BaseModel):
    items: list[ListingOut]
    total: int


class CmaAnalogOut(BaseModel):
    id: int
    source: str
    url: str
    title: str
    price_usd: float
    area_m2: float
    price_per_m2_usd: float
    rooms: int
    floor: Optional[int]
    district: str
    address_raw: str
    seen_at: str


class CmaStatsOut(BaseModel):
    count: int
    avg_price_per_m2_usd: Optional[float]
    median_price_per_m2_usd: Optional[float]
    min_price_per_m2_usd: Optional[float]
    max_price_per_m2_usd: Optional[float]
    avg_price_usd: Optional[float]


class CmaResultOut(BaseModel):
    subject: CmaAnalogOut
    basis: str
    basis_label: str
    area_tolerance_percent: float
    stats: CmaStatsOut
    subject_vs_market_percent: Optional[float]
    analogs: list[CmaAnalogOut]


class ListingEventOut(BaseModel):
    id: int
    event_type: str
    old_price_usd: Optional[float] = None
    new_price_usd: Optional[float] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    source: Optional[str] = None
    source_id: Optional[str] = None
    note: Optional[str] = None
    at: datetime

    model_config = ConfigDict(from_attributes=True)


class ListingHistorySummary(BaseModel):
    first_seen_at: Optional[datetime] = None
    first_price_usd: Optional[float] = None
    current_price_usd: Optional[float] = None
    total_price_change_percent: Optional[float] = None
    price_change_count: int = 0
    relisted_count: int = 0
    last_relisted_at: Optional[datetime] = None
    last_delisted_at: Optional[datetime] = None


class ListingHistoryOut(BaseModel):
    listing_id: int
    summary: ListingHistorySummary
    events: list[ListingEventOut]


class ScrapeRunRequest(BaseModel):
    source: str = "all"
    mode: str = "auto"


class ScrapeRunOut(BaseModel):
    id: int
    source: str
    status: str
    trigger: str = "manual"
    new_count: int
    updated_count: int
    error: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ScrapeSourceOut(BaseModel):
    source: str
    supports_live: bool
    total_pages: Optional[int] = None
    page_size: Optional[int] = None
    total_listings: Optional[int] = None
    error: Optional[str] = None


class ScrapeTaskOut(BaseModel):
    id: int
    status: str
    trigger: str = "manual"
    mode: str
    sources: str
    current_source: Optional[str]
    pages_scanned: int
    found_count: int
    new_count: int
    updated_count: int
    error: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
