from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy import select

from app.bot.keyboards import (
    alert_actions,
    districts_keyboard,
    main_menu,
    rooms_keyboard,
    skip_keyboard,
    start_inline,
)
from app.bot.matcher import describe_alert
from app.bot.states import NewAlert
from app.db.session import SessionLocal
from app.models import Alert, User
from app.services.normalization import CANONICAL_DISTRICTS

router = Router(name="bot.handlers")
logger = logging.getLogger(__name__)


@router.errors()
async def on_bot_error(event: ErrorEvent) -> bool:
    """Не давать одному кривому апдейту валить polling и шуметь трейсбеком.

    Частый безобидный кейс: юзер кликает уже выбранную inline-кнопку →
    мы правим сообщение тем же содержимым, и Телеграм отвечает 400
    "message is not modified". Это не ошибка — глушим молча. Остальное
    логируем (через app.bot logger) и помечаем как обработанное, чтобы
    aiogram не дублировал сырой трейсбек.
    """
    exc = event.exception
    if isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc):
        return True
    logger.error("bot handler failed", exc_info=exc)
    return True

HELP = (
    "🤖 Бот следит за новыми объявлениями по Ташкенту и шлёт вам уведомления, "
    "как только появится подходящая квартира.\n\n"
    "<b>Как пользоваться:</b>\n"
    "1️⃣ Нажмите <b>«➕ Новый алёрт»</b> и за пару шагов задайте фильтр "
    "(район, комнаты, цена…).\n"
    "2️⃣ Бот сам пришлёт уведомление, когда найдётся объявление под ваш фильтр.\n"
    "3️⃣ В <b>«📋 Мои алёрты»</b> можно поставить на паузу или удалить.\n\n"
    "<b>Команды:</b>\n"
    "/new — создать новый алёрт (фильтр)\n"
    "/list — мои алёрты\n"
    "/help — помощь"
)

WELCOME = (
    "Привет! 👋\n\n"
    "Я помогу не пропустить выгодную квартиру в Ташкенте. "
    "Просто нажмите кнопку ниже — настроим за минуту 👇"
)


def _ensure_user(tg_id: int, username: Optional[str], first_name: Optional[str]) -> int:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_id == tg_id))
        if user is None:
            user = User(telegram_id=tg_id, username=username, first_name=first_name)
            db.add(user)
            db.commit()
            db.refresh(user)
        return user.id


def _parse_range(text: str) -> tuple[Optional[float], Optional[float]]:
    """'30000-50000' / '-50000' / '30000-' / '50000'."""
    text = text.strip().replace(" ", "").replace("_", "")
    if not text:
        return None, None
    m = re.match(r"^(\d+(?:\.\d+)?)?-(\d+(?:\.\d+)?)?$", text)
    if m:
        lo = float(m.group(1)) if m.group(1) else None
        hi = float(m.group(2)) if m.group(2) else None
        return lo, hi
    if text.replace(".", "").isdigit():
        return float(text), None
    return None, None


# ---------- /start, /help, menu buttons ----------

@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    _ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    # сначала ставим reply-клавиатуру, затем — крупные inline-кнопки для новичков
    await msg.answer(WELCOME, reply_markup=main_menu())
    await msg.answer("Что хотите сделать?", reply_markup=start_inline())


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(msg: Message) -> None:
    await msg.answer(HELP, reply_markup=main_menu())


# ---------- /new flow ----------

async def _begin_new_alert(msg: Message, user, state: FSMContext) -> None:
    _ensure_user(user.id, user.username, user.first_name)
    await state.clear()
    await state.set_state(NewAlert.districts)
    await state.update_data(districts=set())
    await msg.answer(
        "Шаг 1/6. Выберите районы (можно несколько):",
        reply_markup=districts_keyboard(set()),
    )


@router.message(Command("new"))
@router.message(F.text == "➕ Новый алёрт")
async def cmd_new(msg: Message, state: FSMContext) -> None:
    await _begin_new_alert(msg, msg.from_user, state)


# ---------- inline-кнопки стартового экрана ----------

@router.callback_query(F.data == "start:new")
async def start_new(cb: CallbackQuery, state: FSMContext) -> None:
    await _begin_new_alert(cb.message, cb.from_user, state)
    await cb.answer()


@router.callback_query(F.data == "start:list")
async def start_list(cb: CallbackQuery) -> None:
    await _send_alerts(cb.message, cb.from_user)
    await cb.answer()


@router.callback_query(F.data == "start:help")
async def start_help(cb: CallbackQuery) -> None:
    await cb.message.answer(HELP, reply_markup=main_menu())
    await cb.answer()


@router.callback_query(NewAlert.districts, F.data.startswith("dist:"))
async def on_district(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    selected: set[str] = set(data.get("districts") or set())

    if payload == "any":
        selected.clear()
        await state.update_data(districts=selected)
        await cb.message.edit_reply_markup(reply_markup=districts_keyboard(selected))
        await cb.answer("Сброшено — любой район")
        return

    if payload == "done":
        await state.set_state(NewAlert.rooms)
        await state.update_data(rooms=set())
        await cb.message.edit_text(
            "Шаг 2/6. Сколько комнат?",
            reply_markup=rooms_keyboard(set()),
        )
        await cb.answer()
        return

    idx = int(payload)
    district = CANONICAL_DISTRICTS[idx]
    if district in selected:
        selected.remove(district)
    else:
        selected.add(district)
    await state.update_data(districts=selected)
    await cb.message.edit_reply_markup(reply_markup=districts_keyboard(selected))
    await cb.answer()


@router.callback_query(NewAlert.rooms, F.data.startswith("rooms:"))
async def on_rooms(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    selected: set[int] = set(data.get("rooms") or set())

    if payload == "any":
        selected.clear()
        await state.update_data(rooms=selected)
        await cb.message.edit_reply_markup(reply_markup=rooms_keyboard(selected))
        await cb.answer("Сброшено — любое")
        return

    if payload == "done":
        await state.set_state(NewAlert.price)
        await cb.message.edit_text(
            "Шаг 3/6. Цена в USD. Формат:\n"
            "<code>30000-80000</code> — диапазон\n"
            "<code>-80000</code> — только верхняя граница\n"
            "<code>30000-</code> — только нижняя\n"
            "или нажмите Пропустить.",
            reply_markup=skip_keyboard("price"),
        )
        await cb.answer()
        return

    n = int(payload)
    if n in selected:
        selected.remove(n)
    else:
        selected.add(n)
    await state.update_data(rooms=selected)
    await cb.message.edit_reply_markup(reply_markup=rooms_keyboard(selected))
    await cb.answer()


@router.callback_query(F.data == "skip:price")
async def skip_price(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewAlert.area)
    await cb.message.edit_text(
        "Шаг 4/6. Площадь в м². Формат: <code>40-80</code>, <code>-80</code>, <code>40-</code>.\n"
        "Или Пропустить.",
        reply_markup=skip_keyboard("area"),
    )
    await cb.answer()


@router.message(NewAlert.price)
async def set_price(msg: Message, state: FSMContext) -> None:
    lo, hi = _parse_range(msg.text or "")
    if lo is None and hi is None:
        await msg.answer("Не понял формат. Пример: <code>30000-80000</code>")
        return
    await state.update_data(price_min=lo, price_max=hi)
    await state.set_state(NewAlert.area)
    await msg.answer(
        "Шаг 4/6. Площадь в м². Формат: <code>40-80</code>, <code>-80</code>, <code>40-</code>.\n"
        "Или Пропустить.",
        reply_markup=skip_keyboard("area"),
    )


@router.callback_query(F.data == "skip:area")
async def skip_area(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewAlert.discount)
    await cb.message.edit_text(
        "Шаг 5/6. Минимальная скидка к рынку, % (0–50). Например <code>10</code>.\nИли Пропустить.",
        reply_markup=skip_keyboard("discount"),
    )
    await cb.answer()


@router.message(NewAlert.area)
async def set_area(msg: Message, state: FSMContext) -> None:
    lo, hi = _parse_range(msg.text or "")
    if lo is None and hi is None:
        await msg.answer("Не понял. Пример: <code>40-80</code>")
        return
    await state.update_data(area_min=lo, area_max=hi)
    await state.set_state(NewAlert.discount)
    await msg.answer(
        "Шаг 5/6. Минимальная скидка к рынку, % (0–50). Например <code>10</code>.\nИли Пропустить.",
        reply_markup=skip_keyboard("discount"),
    )


@router.callback_query(F.data == "skip:discount")
async def skip_discount(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewAlert.name)
    await cb.message.edit_text("Шаг 6/6. Как назвать алёрт? Любое короткое имя.")
    await cb.answer()


@router.message(NewAlert.discount)
async def set_discount(msg: Message, state: FSMContext) -> None:
    text = (msg.text or "").strip().replace("%", "")
    try:
        pct = float(text)
    except ValueError:
        await msg.answer("Введите число от 0 до 50 (процентов).")
        return
    if pct < 0 or pct > 50:
        await msg.answer("Введите число от 0 до 50.")
        return
    await state.update_data(discount_min=pct / 100.0)
    await state.set_state(NewAlert.name)
    await msg.answer("Шаг 6/6. Как назвать алёрт? Любое короткое имя.")


@router.message(NewAlert.name)
async def set_name(msg: Message, state: FSMContext) -> None:
    name = (msg.text or "").strip()[:80] or "Без имени"
    data = await state.get_data()
    user_id = _ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)

    districts = sorted(data.get("districts") or set())
    rooms = sorted(int(r) for r in (data.get("rooms") or set()))

    with SessionLocal() as db:
        alert = Alert(
            user_id=user_id,
            name=name,
            districts=",".join(districts) if districts else None,
            rooms=",".join(str(r) for r in rooms) if rooms else None,
            price_min=data.get("price_min"),
            price_max=data.get("price_max"),
            area_min=data.get("area_min"),
            area_max=data.get("area_max"),
            discount_min=data.get("discount_min"),
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        summary = describe_alert(alert)

    await state.clear()
    await msg.answer(
        f"✅ Алёрт <b>«{name}»</b> создан.\n\n{summary}\n\n"
        "Теперь я пришлю сообщение как только появится подходящий листинг.",
        reply_markup=main_menu(),
    )


# ---------- /list ----------

async def _send_alerts(msg: Message, user) -> None:
    user_id = _ensure_user(user.id, user.username, user.first_name)
    with SessionLocal() as db:
        alerts = db.scalars(
            select(Alert).where(Alert.user_id == user_id).order_by(Alert.id.desc())
        ).all()

    if not alerts:
        await msg.answer(
            "Алёртов пока нет. Нажмите «➕ Новый алёрт», чтобы создать первый.",
            reply_markup=main_menu(),
        )
        return

    for a in alerts:
        status = "🟢 активен" if a.is_active else "⏸ на паузе"
        text = f"<b>{a.name}</b> · {status}\n\n{describe_alert(a)}"
        await msg.answer(text, reply_markup=alert_actions(a.id, a.is_active))


@router.message(Command("list"))
@router.message(F.text == "📋 Мои алёрты")
async def cmd_list(msg: Message) -> None:
    await _send_alerts(msg, msg.from_user)


@router.callback_query(F.data.startswith("toggle:"))
async def on_toggle(cb: CallbackQuery) -> None:
    alert_id = int(cb.data.split(":", 1)[1])
    with SessionLocal() as db:
        alert = db.get(Alert, alert_id)
        if alert is None or alert.user_id != _ensure_user(
            cb.from_user.id, cb.from_user.username, cb.from_user.first_name
        ):
            await cb.answer("Не нашёл алёрт.", show_alert=True)
            return
        alert.is_active = not alert.is_active
        db.commit()
        new_state = alert.is_active
        name = alert.name
        summary = describe_alert(alert)

    status = "🟢 активен" if new_state else "⏸ на паузе"
    await cb.message.edit_text(
        f"<b>{name}</b> · {status}\n\n{summary}",
        reply_markup=alert_actions(alert_id, new_state),
    )
    await cb.answer("Готово")


@router.callback_query(F.data.startswith("del:"))
async def on_delete(cb: CallbackQuery) -> None:
    alert_id = int(cb.data.split(":", 1)[1])
    with SessionLocal() as db:
        alert = db.get(Alert, alert_id)
        if alert is None or alert.user_id != _ensure_user(
            cb.from_user.id, cb.from_user.username, cb.from_user.first_name
        ):
            await cb.answer("Не нашёл алёрт.", show_alert=True)
            return
        db.delete(alert)
        db.commit()

    await cb.message.edit_text("🗑 Удалён.")
    await cb.answer()
