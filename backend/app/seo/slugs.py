"""URL-slug'и и человекочитаемые подписи для SEO-хабов.

Районы маппим явной картой (а не транслитом) — даёт короткие URL вида
/kvartira/chilanzar вместо /kvartira/chilanzarskij-rajon. Ключи карты — это
канонические названия из normalization._DISTRICT_ALIASES; всё, что туда не
попало (например «Не указан»), хаба и slug'а не получает.
"""
from __future__ import annotations

import re

DISTRICT_SLUGS: dict[str, str] = {
    "Чиланзарский район": "chilanzar",
    "Мирабадский район": "mirabad",
    "Мирзо-Улугбекский район": "mirzo-ulugbek",
    "Юнусабадский район": "yunusabad",
    "Яккасарайский район": "yakkasaray",
    "Яшнабадский район": "yashnabad",
    "Сергелийский район": "sergeli",
    "Алмазарский район": "almazar",
    "Учтепинский район": "uchtepa",
    "Шайхантахурский район": "shaykhantakhur",
    "Бектемирский район": "bektemir",
    "Янгихаётский район": "yangihayot",
}
SLUG_TO_DISTRICT: dict[str, str] = {slug: name for name, slug in DISTRICT_SLUGS.items()}

# Slug комнатности: «2-komnatnye». Цифра 1..9 — больше в Ташкенте не бывает.
ROOMS_SLUG_RE = re.compile(r"^([1-9])-komnatnye$")


def district_slug(name: str | None) -> str | None:
    return DISTRICT_SLUGS.get(name or "")


def district_from_slug(slug: str) -> str | None:
    return SLUG_TO_DISTRICT.get(slug)


def district_locative(name: str) -> str:
    """«Чиланзарский район» → «Чиланзарском районе» (для «Квартиры в …»).

    Все районы единообразно оканчиваются на «-ский район», поэтому одно
    правило покрывает весь список.
    """
    return name.replace("ский район", "ском районе")


def rooms_slug(rooms: int) -> str:
    return f"{rooms}-komnatnye"


def rooms_from_slug(slug: str) -> int | None:
    match = ROOMS_SLUG_RE.match(slug)
    return int(match.group(1)) if match else None


def rooms_label(rooms: int) -> str:
    return f"{rooms}-комнатные"


# --- ЖК-слаги: /jk/{id}-{translit(name)} -------------------------------------
_COMPLEX_ID_RE = re.compile(r"^(\d+)(?:-.*)?$")

# Русская кириллица → латиница (без внешних зависимостей). Латиница/цифры в
# именах ЖК проходят как есть, кириллица транслитерируется.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _translit(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())


def complex_slug(rc_id: int, name: str) -> str:
    """`/jk/{id}-{транслит-имени}`. Резолвим по id, имя в URL — для SEO."""
    base = re.sub(r"[^a-z0-9]+", "-", _translit(name)).strip("-")
    return f"{rc_id}-{base}" if base else str(rc_id)


def complex_id_from_slug(slug: str) -> int | None:
    match = _COMPLEX_ID_RE.match(slug)
    return int(match.group(1)) if match else None
