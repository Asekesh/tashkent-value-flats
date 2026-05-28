"""Извлечение производных признаков из текста объявления для CMA-фильтрации.

CMA сравнивает квартиры; чтобы аналоги были честными, нужно матчить:
- материал стен (панель/кирпич/монолит — структурно разные цены)
- этаж (1-й/последний дешевле; средние сравниваем ±2)
- год постройки (хрущёвка vs 2010-е vs 2020-е — разные классы)
- микро-локацию (массив/ЖК/блок — район в Ташкенте «лучами» тянется от
  центра к краю, Феруза и Ц-1 формально один район, но разные рынки).

Сегмент (новостройка/вторичка) живёт в [segmentation.py] — используем его
как есть.
"""
from __future__ import annotations

import re


MATERIAL_PANEL = "panel"
MATERIAL_BRICK = "brick"
MATERIAL_MONOLITH = "monolith"


# Порядок важен: более специфичные/составные маркеры первыми, чтобы
# «монолитно-кирпичный» классифицировался как монолит, а не кирпич.
_MATERIAL_MARKERS: tuple[tuple[str, str], ...] = (
    ("монолит", MATERIAL_MONOLITH),
    ("monolit", MATERIAL_MONOLITH),
    ("панельн", MATERIAL_PANEL),
    ("панел", MATERIAL_PANEL),
    ("panel uy", MATERIAL_PANEL),
    ("panel ", MATERIAL_PANEL),
    ("кирпичн", MATERIAL_BRICK),
    ("кирпич", MATERIAL_BRICK),
    ("g'isht", MATERIAL_BRICK),
    ("gisht", MATERIAL_BRICK),
)


def extract_material(*texts: str | None) -> str | None:
    """Достаём материал стен из любого набора текстов. None если ничего не нашли."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    for marker, material in _MATERIAL_MARKERS:
        if marker in blob:
            return material
    return None


# Известные суб-локации Ташкента (массивы/ЖК/исторические районы). Список
# заведомо неполный — главное перехватить самые узнаваемые точки, дальше
# regex-блоки и явный маркер «массив N» добивают остальное.
_KNOWN_LOCATIONS: tuple[str, ...] = (
    "феруза", "себзор", "sebzor", "куйлюк", "куйлук", "qoʻyliq", "qoyliq",
    "каракамыш", "qoraqamish", "чорсу", "chorsu", "хадра", "khadra",
    "дархан", "darxon", "новза", "novza", "лабзак", "сергели", "sergeli",
    "шахристон", "shahriston", "максим горький", "буюк ипак йули",
    "юнусабад", "юнусобод", "yunusabad", "yunusobod",
    "tashkent city", "tashkent-city", "boulevard", "nest one", "nest two",
    "akay city", "millennium", "millenium", "izumrud", "rich house",
    "city park", "manhattan", "asson", "yangi hayot", "golden house",
    "darhan towers", "qushbegi", "novza city",
)


# Блочные идентификаторы: «Ц-1», «С-2», «Q-9», «ТТЗ-3». «ттз» первым
# (длинная альтернатива), иначе движок мог бы поглотить «т» из «ттз» как
# часть «\b» и не дойти до полного префикса.
_BLOCK_PATTERN = re.compile(
    r"\b(ттз|ц|с|q)[\s\-]?(\d{1,2})\b",
    re.IGNORECASE,
)

_MASSIV_PATTERN = re.compile(r"масс?ив\s+([\wа-яё0-9\-]{2,30})", re.IGNORECASE)
_KVARTAL_PATTERN = re.compile(r"квартал\s+([\wа-яё0-9\-]{2,30})", re.IGNORECASE)


def extract_micro_location(*texts: str | None) -> str | None:
    """Достаём токен суб-локации (массив/ЖК/блок). None если сигнала нет."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    m = _MASSIV_PATTERN.search(blob)
    if m:
        return _canon(m.group(1))
    m = _KVARTAL_PATTERN.search(blob)
    if m:
        return _canon(f"квартал-{m.group(1)}")
    m = _BLOCK_PATTERN.search(blob)
    if m:
        return _canon(f"{m.group(1)}-{m.group(2)}")
    for token in _KNOWN_LOCATIONS:
        if token in blob:
            return _canon(token)
    return None


def _canon(token: str) -> str:
    return re.sub(r"\s+", "-", token.strip().lower())


_YEAR_HINTS: tuple[str, ...] = (
    "год постройки", "построен в", "построен ", "год сдачи", "сдан в",
    "qurilgan yili", "qurilish yili",
)


def extract_year(*texts: str | None) -> int | None:
    """Год постройки из любого набора текстов. None если не нашли."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    for hint in _YEAR_HINTS:
        idx = blob.find(hint)
        if idx < 0:
            continue
        window = blob[idx + len(hint) : idx + len(hint) + 16]
        digits: list[str] = []
        for ch in window:
            if ch.isdigit():
                digits.append(ch)
                if len(digits) == 4:
                    break
            elif digits:
                digits = []
        if len(digits) == 4:
            year = int("".join(digits))
            if 1900 <= year <= 2099:
                return year
    return None


def years_close(a: int | None, b: int | None, max_gap: int = 15) -> bool:
    """Годы постройки считаются «той же эпохой» если разница ≤15 лет.
    Если хоть один неизвестен — не блокируем матч (нет данных = не повод
    выкинуть кандидата)."""
    if a is None or b is None:
        return True
    return abs(a - b) <= max_gap


def floors_close(a: int | None, b: int | None, max_gap: int = 2) -> bool:
    """Этажи считаются близкими если разница ≤2. Неизвестный этаж не блокирует."""
    if a is None or b is None:
        return True
    return abs(a - b) <= max_gap
