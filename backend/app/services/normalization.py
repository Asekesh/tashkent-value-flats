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


CANONICAL_DISTRICTS = [
    "Чиланзарский район",
    "Мирабадский район",
    "Мирзо-Улугбекский район",
    "Юнусабадский район",
    "Яккасарайский район",
    "Яшнабадский район",
    "Сергелийский район",
    "Алмазарский район",
    "Учтепинский район",
    "Шайхантахурский район",
    "Бектемирский район",
    "Янгихаётский район",
]

_DISTRICT_ALIASES = (
    ("чиланзар", "Чиланзарский район"),
    ("чилонзор", "Чиланзарский район"),
    ("chilanzar", "Чиланзарский район"),
    ("мираба", "Мирабадский район"),
    ("mirabad", "Мирабадский район"),
    ("мирзо", "Мирзо-Улугбекский район"),
    ("улугбек", "Мирзо-Улугбекский район"),
    ("mirzo", "Мирзо-Улугбекский район"),
    ("ulugbek", "Мирзо-Улугбекский район"),
    ("юнусабад", "Юнусабадский район"),
    ("юнус-абад", "Юнусабадский район"),
    ("yunusabad", "Юнусабадский район"),
    ("yunus", "Юнусабадский район"),
    ("яккасарай", "Яккасарайский район"),
    ("yakkasaray", "Яккасарайский район"),
    ("яшнабад", "Яшнабадский район"),
    ("yashnobod", "Яшнабадский район"),
    ("yashnabad", "Яшнабадский район"),
    ("сергел", "Сергелийский район"),
    ("sergeli", "Сергелийский район"),
    ("алмазар", "Алмазарский район"),
    ("олмазор", "Алмазарский район"),
    ("almazar", "Алмазарский район"),
    ("учтеп", "Учтепинский район"),
    ("uchtepa", "Учтепинский район"),
    ("шайхантахур", "Шайхантахурский район"),
    ("шайхонтохур", "Шайхантахурский район"),
    ("shaykhantakhur", "Шайхантахурский район"),
    ("shayxontoxur", "Шайхантахурский район"),
    ("бектемир", "Бектемирский район"),
    ("bektemir", "Бектемирский район"),
    ("янгихаёт", "Янгихаётский район"),
    ("янгихает", "Янгихаётский район"),
    ("yangihayot", "Янгихаётский район"),
)


def normalize_district(value: str | None) -> str:
    text = compact_text(value).replace("р-н", "район").replace("рн", "район")
    lowered = text.lower()
    for key, district in _DISTRICT_ALIASES:
        if key in lowered:
            return district
    return "Не указан"


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


# --- ЖК-нормализатор (Шаг 3e) ---------------------------------------------
# Имя ЖК у источников почти не приходит структурно (Uybor отдаёт только
# residentialComplexId без имени, заполнен он у ~2% объявлений), зато сплошь
# и рядом сидит в тексте адреса/описания: «ЖК Nest One», «жилой комплекс
# Паркент Плаза», «в ЖК OzMakon». Поэтому тянем имя из текста, а склейку
# разных написаний («Mirabad Avenue / Мирабад Авеню / mirabad avenue») делаем
# через транслитерированный match_key.

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # узбекская кириллица
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}

# Хвостовые «адресные» токены, которые жадный захват имени мог прихватить
# после настоящего названия («ЖК IMPERIAL Club City Адрес : ...»).
_COMPLEX_STOPWORDS = {
    "адрес", "район", "ориентир", "метро", "дом", "улица", "проспект",
    "массив", "квартал", "новостройка", "кв", "near", "возле", "рядом",
    "продается", "продаётся", "сдается", "сдаётся", "этаж", "мкр", "мфй",
    # «ЖК» внутри имени = склейка двух упоминаний («Мирабад Авеню ЖК Mirabad»);
    # «от/на» и «застрой(щик)» — хвост вроде «OzMakon от Golden House».
    "жк", "от", "на", "в", "застрой", "застройщик", "residential", "complex",
}

# keyword (без регистра, не часть другого слова) + опц. кавычки/тире +
# имя: первый токен с буквы, до 3 продолжений с заглавной/цифры.
_COMPLEX_RE = re.compile(
    r"(?i:(?<![A-Za-zА-Яа-яЁё0-9])(?:жк|ж/к|ж\.\s?к|жилой\s+комплекс|residential\s+complex))"
    r"[\s:«»\"'`\-–—]*"
    r"([A-Za-zА-ЯЁ][\w&.\-]*(?:\s+[A-Za-zА-Яа-яЁё][\w&.\-]*){0,3})"
)


def transliterate(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())


def complex_match_key(name: str) -> str:
    """Ключ склейки ЖК: транслит кириллицы в латиницу, только [a-z0-9].
    «Nest One» / «нест ван»? нет — но «Mirabad Avenue» == «mirabad avenue»."""
    return re.sub(r"[^a-z0-9]+", "", transliterate(name or ""))


def extract_complex_name(text: str | None) -> str | None:
    """Достаёт каноничное имя ЖК из свободного текста или None."""
    if not text:
        return None
    match = _COMPLEX_RE.search(text)
    if not match:
        return None
    tokens = match.group(1).split()
    kept: list[str] = []
    for token in tokens:
        if token.lower().strip(".") in _COMPLEX_STOPWORDS:
            break
        kept.append(token)
    name = compact_text(" ".join(kept))
    if len(complex_match_key(name)) < 2:
        return None
    return name


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
