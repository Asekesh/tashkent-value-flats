from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from app.bot.i18n import DEFAULT_LANG, area_label, floor_label, rooms_label, t
from app.services.normalization import CANONICAL_DISTRICTS


def main_menu(lang: str = DEFAULT_LANG) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("b_new", lang)), KeyboardButton(text=t("b_list", lang))],
            [KeyboardButton(text=t("b_feedback", lang)), KeyboardButton(text=t("b_help", lang))],
            [KeyboardButton(text=t("b_lang", lang))],
        ],
        resize_keyboard=True,
        input_field_placeholder=t("placeholder", lang),
    )


def start_inline(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Большая заметная кнопка на экране /start для новичков."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("b_start_new", lang), callback_data="start:new")],
            [InlineKeyboardButton(text=t("b_list", lang), callback_data="start:list")],
            [InlineKeyboardButton(text=t("b_feedback", lang), callback_data="start:feedback")],
            [InlineKeyboardButton(text=t("b_how", lang), callback_data="start:help")],
        ]
    )


def lang_keyboard() -> InlineKeyboardMarkup:
    """Выбор языка интерфейса. Подписи двуязычные — не зависят от текущего lang."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=t("b_lang_ru"), callback_data="setlang:ru"),
            InlineKeyboardButton(text=t("b_lang_uz"), callback_data="setlang:uz"),
        ]]
    )


def feedback_kind_keyboard(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=t("b_bug", lang), callback_data="fb:bug"),
            InlineKeyboardButton(text=t("b_feature", lang), callback_data="fb:feature"),
        ]]
    )


def districts_keyboard(selected: set[str], lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, district in enumerate(CANONICAL_DISTRICTS):
        prefix = "✅ " if district in selected else "▫️ "
        short = district.replace("ский район", "").replace(" район", "")
        row.append(InlineKeyboardButton(text=prefix + short, callback_data=f"dist:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text=t("b_any_district", lang), callback_data="dist:any"),
        InlineKeyboardButton(text=t("b_done", lang), callback_data="dist:done"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rooms_keyboard(selected: set[int], lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    def btn(n: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=("✅ " if n in selected else "▫️ ") + rooms_label(n, lang),
            callback_data=f"rooms:{n}",
        )

    rows = [
        [btn(1), btn(2), btn(3)],
        [btn(4), btn(5), btn(6)],
    ]
    rows.append([
        InlineKeyboardButton(text=t("b_any_rooms", lang), callback_data="rooms:any"),
        InlineKeyboardButton(text=t("b_done", lang), callback_data="rooms:done"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Набор значений для выбора границ «от» / «до».
PRICE_VALUES: list[int] = [
    20_000, 30_000, 40_000, 50_000, 60_000, 70_000,
    85_000, 100_000, 120_000, 150_000, 200_000, 300_000,
]

# Помесячные пресеты для аренды ($/мес). Отдельный набор — масштаб иной, чем sale.
PRICE_VALUES_RENT: list[int] = [200, 300, 400, 500, 700, 1000, 1500, 2000, 3000]


def _price_values(deal_type: str) -> list[int]:
    return PRICE_VALUES_RENT if deal_type == "rent" else PRICE_VALUES
AREA_VALUES: list[int] = [20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 150, 200]


def fmt_price(v: int) -> str:
    return f"${v // 1000}k"


def _bounds_keyboard(
    prefix: str, values: list[int], fmt, any_label: str, only_after: int | None = None
) -> InlineKeyboardMarkup:
    """Сетка цифр для выбора одной границы. only_after — индекс «от», чтобы
    в шаге «до» показывать только значения больше выбранного минимума."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, value in enumerate(values):
        if only_after is not None and idx <= only_after:
            continue
        row.append(InlineKeyboardButton(text=fmt(value), callback_data=f"{prefix}:{idx}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text=any_label, callback_data=f"{prefix}:any")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def price_from_keyboard(lang: str = DEFAULT_LANG, deal_type: str = "sale") -> InlineKeyboardMarkup:
    return _bounds_keyboard("pmin", _price_values(deal_type), fmt_price, t("b_unimportant", lang))


def price_to_keyboard(min_idx: int | None, lang: str = DEFAULT_LANG, deal_type: str = "sale") -> InlineKeyboardMarkup:
    return _bounds_keyboard("pmax", _price_values(deal_type), fmt_price, t("b_no_upper", lang), only_after=min_idx)


def area_from_keyboard(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    fmt = lambda v: area_label(v, lang)
    return _bounds_keyboard("amin", AREA_VALUES, fmt, t("b_unimportant", lang))


def area_to_keyboard(min_idx: int | None, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    fmt = lambda v: area_label(v, lang)
    return _bounds_keyboard("amax", AREA_VALUES, fmt, t("b_no_upper", lang), only_after=min_idx)


FLOOR_VALUES: list[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16]


def floor_from_keyboard(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    fmt = lambda v: floor_label(v, lang)
    return _bounds_keyboard("fmin", FLOOR_VALUES, fmt, t("b_unimportant", lang))


def floor_to_keyboard(min_idx: int | None, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    fmt = lambda v: floor_label(v, lang)
    return _bounds_keyboard("fmax", FLOOR_VALUES, fmt, t("b_no_upper", lang), only_after=min_idx)


# (подпись, доля 0..1)
DISCOUNT_PRESETS: list[tuple[str, float]] = [
    ("≥ 5%", 0.05),
    ("≥ 10%", 0.10),
    ("≥ 15%", 0.15),
    ("≥ 20%", 0.20),
    ("≥ 25%", 0.25),
    ("≥ 30%", 0.30),
]


def _preset_keyboard(prefix: str, labels: list[str], any_label: str, per_row: int = 2) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, label in enumerate(labels):
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{idx}"))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text=any_label, callback_data=f"{prefix}:any")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def discount_keyboard(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return _preset_keyboard("disc", [p[0] for p in DISCOUNT_PRESETS], t("b_any_discount", lang), per_row=3)


def deal_type_keyboard(selected: str = "sale", lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Тумблер Продажа/Аренда с галочкой у выбранного + кнопка «Готово»."""
    def mark(code: str, label: str) -> str:
        return ("✓ " + label) if selected == code else label
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=mark("sale", t("b_deal_sale", lang)), callback_data="deal:sale"),
            InlineKeyboardButton(text=mark("rent", t("b_deal_rent", lang)), callback_data="deal:rent"),
        ],
        [InlineKeyboardButton(text=t("b_done", lang), callback_data="deal:done")],
    ])


def commission_keyboard(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Шаг аренды: без комиссии / неважно."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("b_no_commission", lang), callback_data="comm:yes"),
        InlineKeyboardButton(text=t("b_unimportant", lang), callback_data="comm:any"),
    ]])


def alert_actions(alert_id: int, is_active: bool, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    toggle_label = t("b_pause", lang) if is_active else t("b_enable", lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_label, callback_data=f"toggle:{alert_id}"),
                InlineKeyboardButton(text=t("b_delete", lang), callback_data=f"del:{alert_id}"),
            ],
            [InlineKeyboardButton(text=t("b_edit", lang), callback_data=f"edit:{alert_id}")],
        ]
    )
