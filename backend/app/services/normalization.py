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

# Листинговый/маркетинговый шум, который засоряет имя ЖК в адресе+описании
# («ЖК Nest One вид», «Mirabad Avenue Мирабадский ID Срочно»). Выкидываем его из
# ключа склейки, НО НЕ трогаем бренд-слова (avenue/plaza/tower/city/house/
# residence/club/gardens) — иначе «Parkent Plaza» и «Parkent Avenue» схлопнулись
# бы в один ЖК. Формы — транслитерированные (см. transliterate). Подобрано по
# реальным 2073 ЖК прода (топ-вокабуляр хвостов).
_COMPLEX_NOISE = {
    "zhk", "zhiloy", "kompleks", "residential", "complex", "id", "adres",
    "srochno", "srochnaya", "srochnuyu", "gorod", "goroda", "menyaetsya", "vash",
    "uvazhaemye", "gosti", "kvartira", "kvartiry", "kvartir", "kvartiru",
    "arenda", "arendu", "arenduyu", "arendoy", "prodam", "prodayu", "prodazha",
    "prodaetsya", "sdaetsya", "sdam", "sdayu", "evro", "evroremont", "evrolyuks",
    "remont", "remontom", "novaya", "novyy", "novoe", "novostroyka", "vid",
    "vidom", "korobka", "penthaus", "studiya", "studiyu", "komnata", "komnat",
    "komnaty", "komnatu", "ploshchad", "etazh", "dom", "doma", "ulitsa", "ul",
    "prospekt", "massiv", "kvartal", "mkr", "mfy", "orientir", "ryadom", "vozle",
    "near", "metro", "elitnyy", "elitnaya", "elitnom", "shikarnaya", "idealno",
    "idealnaya", "polnostyu", "dlya", "vse", "vsemi", "eksklyuziv", "tsentr",
    "vpervye", "predlagaetsya", "toropites", "zhivite", "neboskreb", "teplaya",
    "chistaya", "avtorskiy", "avtorskim", "kirpich", "kirpichnyy", "dvor",
    "gotovye", "gotovaya", "predlozhenie", "unikalnoe", "unikalnaya",
    "sovremennyy", "potryasayushchiy", "prosto", "samaya", "pervaya", "liniya",
    "sostoyanie", "harakteristiki", "osnovnye", "posrednikov", "bez",
    "nahoditsya", "lyuks", "pod", "mebel", "tehnika", "sistema", "umnyy",
    "dolgosrochnaya", "posutochnaya", "apartment", "for", "sale", "rent",
    "urgent", "ot", "na", "zastroy", "zastroyshchik",
    "blok", "block", "bloka", "korpus", "korpusa", "blic", "blok",
}
# Район-токены (целые слова) и хвост «-ский/-ская» — всегда адресный шум.
_DISTRICT_TOKENS = {"rayon", "rn", "mahalla"}
_DISTRICT_SUFFIX_RE = re.compile(r"(skiy|skoy|skij|skaya)$")

# EN↔RU фонетический канон заимствований: кириллическое и латинское написание
# одного ЖК должны дать один ключ («Акай Сити»==«Akay City», «Мирабад Авеню»==
# «Mirabad Avenue», «Резиденс»==«Residence»). Маппинг узкий и безопасный —
# только заимствованные хвосты-бренды.
_PHONETIC_CANON = {
    "avenyu": "avenue", "aveny": "avenue", "avenu": "avenue",
    "siti": "city",
    "rezidens": "residence", "residens": "residence", "rezidence": "residence",
    "haus": "house", "hause": "house",
    "klab": "club", "klub": "club",
    "tauer": "tower", "tawer": "tower",
    "layf": "life",
    "bulvar": "boulevard",
    "viladzh": "village", "vilage": "village", "villadzh": "village",
    "garden": "gardens",
}

# keyword (без регистра, не часть другого слова) + опц. кавычки/тире + имя:
# первый токен с буквы, до 5 продолжений (с запасом — лишний адресный/шумовой
# хвост всё равно срежется в _complex_tokens).
_COMPLEX_RE = re.compile(
    r"(?i:(?<![A-Za-zА-Яа-яЁё0-9])(?:жк|ж/к|ж\.\s?к|жилой\s+комплекс|residential\s+complex))"
    r"[\s:«»“”‘’„‟\"'`\-–—]*"
    r"([A-Za-zА-ЯЁ][\w&.\-]*(?:\s+[A-Za-zА-Яа-яЁё][\w&.\-]*){0,5})"
)

_COMPLEX_TOKEN_SPLIT = re.compile(r"[^0-9A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ]+")


def transliterate(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())


def _is_plain_noise(canon: str) -> bool:
    """Безусловный шум: листинговые/маркетинговые слова, цифры, одиночные буквы,
    коды объявлений. Всегда выкидываем И останавливаем на нём захват имени."""
    if canon in _COMPLEX_NOISE:
        return True
    if canon.isdigit() or len(canon) == 1:
        return True
    if re.fullmatch(r"u\d?k\d?", canon):  # «У7К4»-коды объявлений
        return True
    if re.fullmatch(r"id\d*", canon):
        return True
    if re.fullmatch(r"[abr]\d+", canon):  # блок-коды A-3 / R1 / B2
        return True
    return False


def _is_district_token(canon: str) -> bool:
    """Район/«-ский». Выкидываем УСЛОВНО — только если в имени есть и бренд-токен
    (иначе «Новомосковская»/«Паркентский» как имя ЖК выродились бы в пустой ключ)."""
    return canon in _DISTRICT_TOKENS or bool(_DISTRICT_SUFFIX_RE.search(canon))


def _complex_tokens(name: str | None) -> list[tuple[str, str]]:
    """[(оригинальный токен для показа, канон-токен для ключа)], без шума.
    Район-токены режем, только если остаётся хотя бы один бренд-токен."""
    raw_list: list[tuple[str, str, bool]] = []
    for raw in _COMPLEX_TOKEN_SPLIT.split(name or ""):
        if not raw:
            continue
        canon = re.sub(r"[^a-z0-9]+", "", transliterate(raw))
        if not canon or _is_plain_noise(canon):
            continue
        raw_list.append((raw, canon, _is_district_token(canon)))
    has_brand = any(not is_dist for _, _, is_dist in raw_list)
    out: list[tuple[str, str]] = []
    for raw, canon, is_dist in raw_list:
        if is_dist and has_brand:
            continue
        out.append((raw, _PHONETIC_CANON.get(canon, canon)))
    return out


def complex_match_key(name: str) -> str:
    """Ключ склейки ЖК: транслит + выкидываем листинговый шум и район-хвосты +
    EN↔RU канон. «Nest One вид»==«Nest One», «Акай Сити»==«Akay City», но
    «Parkent Plaza»≠«Parkent Avenue» (бренд-слова сохраняются)."""
    return "".join(canon for _, canon in _complex_tokens(name))


def clean_complex_name(name: str | None) -> str:
    """Чистое имя ЖК для показа: те же не-шумовые токены в оригинальном
    написании, максимум 4 (длиннее имён у ЖК практически нет)."""
    return compact_text(" ".join(raw for raw, _ in _complex_tokens(name)[:4]))


def extract_complex_name(text: str | None) -> str | None:
    """Достаёт каноничное имя ЖК из свободного текста или None.

    Берём ВЕДУЩИЙ ран не-шумовых токенов и стоп на первом шумовом — он граница
    названия: «ЖК Nest One вид на парк» → «Nest One» (не «Nest One Парк»).
    Этим extract отличается от complex_match_key/clean_complex_name, которые
    выкидывают шум по всей строке (нужно, чтобы перекючевать УЖЕ сохранённые
    шумные имена вроде «Nest One вид» при ремердже)."""
    if not text:
        return None
    match = _COMPLEX_RE.search(text)
    if not match:
        return None
    # Берём ведущий ран токенов до первого ПЛОСКОГО шума (он граница названия).
    # Район-токены не граница — собираем, а лишние срежем по has_brand ниже.
    collected: list[tuple[str, bool]] = []
    for raw in _COMPLEX_TOKEN_SPLIT.split(match.group(1)):
        if not raw:
            continue
        canon = re.sub(r"[^a-z0-9]+", "", transliterate(raw))
        if not canon:
            continue
        if _is_plain_noise(canon):
            break
        collected.append((raw, _is_district_token(canon)))
        if len(collected) >= 6:
            break
    has_brand = any(not is_dist for _, is_dist in collected)
    kept = [raw for raw, is_dist in collected if not (is_dist and has_brand)][:4]
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
