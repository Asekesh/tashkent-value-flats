from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from statistics import median
from typing import Any


USD_TO_UZS = 12700


def compact_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def parse_number(value: str | int | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = value.replace(",", ".")
    cleaned = re.sub(r"[^\d.]", "", cleaned)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_currency(value: str | None) -> str:
    text = (value or "").lower()
    if "$" in text or "у.е" in text or "usd" in text:
        return "USD"
    if "сум" in text or "uzs" in text:
        return "UZS"
    return "USD"


def to_usd(price: float, currency: str) -> float:
    if currency.upper() == "UZS":
        return round(price / USD_TO_UZS, 2)
    return round(price, 2)


def price_per_m2(price_usd: float, area_m2: float) -> float:
    if area_m2 <= 0:
        raise ValueError("area_m2 must be positive")
    return round(price_usd / area_m2, 2)


def parse_floor(value: str | None) -> tuple[int | None, int | None]:
    text = compact_text(value)
    if not text:
        return None, None
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1)), None
    return None, None


def normalize_district(value: str | None) -> str:
    text = compact_text(value).replace("р-н", "район").replace("рн", "район")
    aliases = {
        "чиланзар": "Чиланзарский район",
        "чилонзор": "Чиланзарский район",
        "мираба": "Мирабадский район",
        "мирзо": "Мирзо-Улугбекский район",
        "юнусабад": "Юнусабадский район",
        "яккасарай": "Яккасарайский район",
        "яшнабад": "Яшнабадский район",
        "сергел": "Сергелийский район",
        "алмазар": "Алмазарский район",
        "учтеп": "Учтепинский район",
        "шайхантахур": "Шайхантахурский район",
        "бектемир": "Бектемирский район",
    }
    lowered = text.lower()
    for key, district in aliases.items():
        if key in lowered:
            return district
    return text or "Не указан"


def normalize_building_key(district: str, address: str | None) -> str | None:
    address_text = compact_text(address).lower()
    if not address_text:
        return None
    normalized = re.sub(r"[^\wа-яё0-9]+", " ", address_text, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(ул|улица|дом|д|кв|ориентир|возле)\b", " ", normalized)
    normalized = compact_text(normalized)
    if len(normalized) < 5:
        return None
    return f"{normalize_district(district).lower()}::{normalized[:180]}"


def duplicate_group_key(district: str, address: str, rooms: int, area_m2: float, price_usd: float) -> str:
    area_bucket = round(area_m2 / 2) * 2
    price_bucket = round(price_usd / 2500) * 2500
    basis = f"{normalize_district(district)}|{compact_text(address).lower()}|{rooms}|{area_bucket}|{price_bucket}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def median_price(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 2)


def utcnow() -> datetime:
    return datetime.utcnow()
