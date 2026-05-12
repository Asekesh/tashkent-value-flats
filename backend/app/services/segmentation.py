from __future__ import annotations


SEGMENT_NEW = "new"
SEGMENT_SECONDARY = "secondary"


# Явные текстовые маркеры новостройки. Совпадение → новостройка.
_NEWBUILD_MARKERS: tuple[str, ...] = (
    "новостройка",
    "новостройки",
    "новостройке",
    "новостроек",
    "новый дом",
    "жк ",
    "жк-",
    "жилой комплекс",
    "сдан в эксплуатацию",
    "ввод в эксплуатацию",
    "комфорт-класс",
    "бизнес-класс",
    "премиум-класс",
    "эконом-класс",
    "yangi qurilish",
    "yangi uy",
    "yangi bino",
    "turar joy majmuasi",
)

# Брендовые названия известных ЖК в Ташкенте. Список заведомо неполный —
# главное покрыть самые громкие, остальное доберёт год постройки или явный
# маркер «новостройка». Лучше пропустить пару новостроек как «secondary»,
# чем массово красить вторичку в new.
_NEWBUILD_BRAND_TOKENS: tuple[str, ...] = (
    "boulevard",
    "nest one",
    "nest two",
    "tashkent city",
    "tashkent-city",
    "yangi uzbekistan",
    "yangi o'zbekiston",
    "akay city",
    "rich house",
    "izumrud",
    "qushbegi",
    "darhan towers",
    "yangi hayot",
    "novza city",
    "asson",
    "millenium",
    "millennium",
    "golden house",
    "manhattan",
    "city park",
)

# Прямые признаки старого фонда. Совпадение → вторичка, даже если рядом
# есть «жк» в шумном тексте.
_SECONDARY_MARKERS: tuple[str, ...] = (
    "массив",
    "квартал",
    "хрущёв",
    "хрущев",
    "сталинк",
    "брежневк",
    "ленинградк",
    "малосемейк",
    "старый фонд",
    "eski uy",
    "panel uy",
)

# Эвристика по году постройки: >=2015 считаем новостройкой.
_NEWBUILD_YEAR_THRESHOLD = 2015
_YEAR_PATTERN_HINTS: tuple[str, ...] = (
    "год постройки",
    "построен в",
    "построен ",
    "год сдачи",
    "qurilgan yili",
    "qurilish yili",
)


def _extract_year(blob: str) -> int | None:
    """Ищем 4-значный год после маркера «год постройки/сдачи». Без жёсткого
    регэкспа — простой пробег по подстрокам, достаточно для шумных описаний."""
    for hint in _YEAR_PATTERN_HINTS:
        idx = blob.find(hint)
        if idx < 0:
            continue
        # окно ~16 символов после маркера, ищем первое 4-значное число 19xx/20xx
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


def classify_segment(
    title: str | None,
    address_raw: str | None,
    description: str | None,
) -> str:
    """Грубо классифицирует объявление: новостройка vs вторичка.

    Логика приоритетов:
      1. Явный маркер новостройки в тексте → new.
      2. Брендовое имя ЖК → new.
      3. Год постройки ≥2015 → new.
      4. Явный маркер вторички / старого фонда → secondary.
      5. По умолчанию — secondary (в Ташкенте вторичка статистически чаще
         встречается без явной пометки, чем новостройка без неё).

    Цель — не идеальная точность, а отделить системно дешёвый старый фонд
    от новостроек, чтобы медиана $/м² считалась внутри однородной группы.
    """
    parts = [p for p in (title, address_raw, description) if p]
    if not parts:
        return SEGMENT_SECONDARY
    blob = " ".join(parts).lower()

    if any(marker in blob for marker in _NEWBUILD_MARKERS):
        return SEGMENT_NEW
    if any(brand in blob for brand in _NEWBUILD_BRAND_TOKENS):
        return SEGMENT_NEW
    year = _extract_year(blob)
    if year is not None and year >= _NEWBUILD_YEAR_THRESHOLD:
        return SEGMENT_NEW
    if any(marker in blob for marker in _SECONDARY_MARKERS):
        return SEGMENT_SECONDARY
    return SEGMENT_SECONDARY


def is_extreme_floor(floor: int | None, total_floors: int | None) -> bool:
    """1-й или последний этаж — структурно дешевле остальных, исключаем
    их из расчёта медианы и не считаем для них дисконт в v1 (база сравнения
    ненадёжна). Если этаж неизвестен — считаем обычным."""
    if floor is None:
        return False
    if floor <= 1:
        return True
    if total_floors is not None and total_floors >= 2 and floor >= total_floors:
        return True
    return False
