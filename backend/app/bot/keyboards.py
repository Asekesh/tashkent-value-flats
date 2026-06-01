from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from app.services.normalization import CANONICAL_DISTRICTS


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новое уведомление"), KeyboardButton(text="📋 Мои уведомления")],
            [KeyboardButton(text="✍️ Обратная связь"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Нажмите кнопку ниже 👇",
    )


def start_inline() -> InlineKeyboardMarkup:
    """Большая заметная кнопка на экране /start для новичков."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать уведомление о новых квартирах", callback_data="start:new")],
            [InlineKeyboardButton(text="📋 Мои уведомления", callback_data="start:list")],
            [InlineKeyboardButton(text="✍️ Обратная связь", callback_data="start:feedback")],
            [InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="start:help")],
        ]
    )


def feedback_kind_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🐞 Ошибка", callback_data="fb:bug"),
            InlineKeyboardButton(text="💡 Пожелание", callback_data="fb:feature"),
        ]]
    )


def districts_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
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
        InlineKeyboardButton(text="🌐 Любой", callback_data="dist:any"),
        InlineKeyboardButton(text="✔️ Готово", callback_data="dist:done"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rooms_keyboard(selected: set[int]) -> InlineKeyboardMarkup:
    def btn(n: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=("✅ " if n in selected else "▫️ ") + f"{n}к",
            callback_data=f"rooms:{n}",
        )

    rows = [
        [btn(1), btn(2), btn(3)],
        [btn(4), btn(5), btn(6)],
    ]
    rows.append([
        InlineKeyboardButton(text="🌐 Любое", callback_data="rooms:any"),
        InlineKeyboardButton(text="✔️ Готово", callback_data="rooms:done"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Набор значений для выбора границ «от» / «до».
PRICE_VALUES: list[int] = [
    20_000, 30_000, 40_000, 50_000, 60_000, 70_000,
    85_000, 100_000, 120_000, 150_000, 200_000, 300_000,
]
AREA_VALUES: list[int] = [20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 150, 200]


def fmt_price(v: int) -> str:
    return f"${v // 1000}k"


def fmt_area(v: int) -> str:
    return f"{v} м²"


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


def price_from_keyboard() -> InlineKeyboardMarkup:
    return _bounds_keyboard("pmin", PRICE_VALUES, fmt_price, "🌐 Неважно")


def price_to_keyboard(min_idx: int | None) -> InlineKeyboardMarkup:
    return _bounds_keyboard("pmax", PRICE_VALUES, fmt_price, "🌐 Без верхней границы", only_after=min_idx)


def area_from_keyboard() -> InlineKeyboardMarkup:
    return _bounds_keyboard("amin", AREA_VALUES, fmt_area, "🌐 Неважно")


def area_to_keyboard(min_idx: int | None) -> InlineKeyboardMarkup:
    return _bounds_keyboard("amax", AREA_VALUES, fmt_area, "🌐 Без верхней границы", only_after=min_idx)


FLOOR_VALUES: list[int] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16]


def fmt_floor(v: int) -> str:
    return f"{v} эт."


def floor_from_keyboard() -> InlineKeyboardMarkup:
    return _bounds_keyboard("fmin", FLOOR_VALUES, fmt_floor, "🌐 Неважно")


def floor_to_keyboard(min_idx: int | None) -> InlineKeyboardMarkup:
    return _bounds_keyboard("fmax", FLOOR_VALUES, fmt_floor, "🌐 Без верхней границы", only_after=min_idx)


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


def discount_keyboard() -> InlineKeyboardMarkup:
    return _preset_keyboard("disc", [p[0] for p in DISCOUNT_PRESETS], "🌐 Любая (не важно)", per_row=3)


def alert_actions(alert_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_label = "⏸ Пауза" if is_active else "▶️ Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_label, callback_data=f"toggle:{alert_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{alert_id}"),
            ],
            [InlineKeyboardButton(text="✏️ Изменить фильтр", callback_data=f"edit:{alert_id}")],
        ]
    )
