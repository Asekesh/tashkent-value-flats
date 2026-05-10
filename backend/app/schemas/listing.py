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


class ScrapeRunRequest(BaseModel):
    source: str = "all"
    mode: str = "auto"


class ScrapeRunOut(BaseModel):
    id: int
    source: str
    status: str
    new_count: int
    updated_count: int
    error: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
