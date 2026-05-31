from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from app.services.normalization import CANONICAL_DISTRICTS


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новый алёрт"), KeyboardButton(text="📋 Мои алёрты")],
            [KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
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
    rows = [[
        InlineKeyboardButton(
            text=("✅ " if n in selected else "▫️ ") + f"{n}к",
            callback_data=f"rooms:{n}",
        )
        for n in (1, 2, 3, 4)
    ]]
    rows.append([
        InlineKeyboardButton(text="🌐 Любое", callback_data="rooms:any"),
        InlineKeyboardButton(text="✔️ Готово", callback_data="rooms:done"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def skip_keyboard(field: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip:{field}")]]
    )


def alert_actions(alert_id: int, is_active: bool) -> InlineKeyboardMarkup:
    toggle_label = "⏸ Пауза" if is_active else "▶️ Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=toggle_label, callback_data=f"toggle:{alert_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{alert_id}"),
        ]]
    )
