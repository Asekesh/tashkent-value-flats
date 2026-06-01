from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy import select

from app.bot.keyboards import (
    AREA_VALUES,
    DISCOUNT_PRESETS,
    FLOOR_VALUES,
    PRICE_VALUES,
    alert_actions,
    area_from_keyboard,
    area_to_keyboard,
    discount_keyboard,
    districts_keyboard,
    floor_from_keyboard,
    floor_to_keyboard,
    main_menu,
    price_from_keyboard,
    price_to_keyboard,
    rooms_keyboard,
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
    "1️⃣ Нажмите <b>«➕ Новое уведомление»</b> и за пару шагов задайте фильтр "
    "(район, комнаты, цена…).\n"
    "2️⃣ Бот сам пришлёт сообщение, когда найдётся квартира под ваш фильтр.\n"
    "3️⃣ В <b>«📋 Мои уведомления»</b> можно поставить на паузу или удалить.\n\n"
    "<b>Команды:</b>\n"
    "/new — настроить уведомления о новых квартирах\n"
    "/list — мои уведомления\n"
    "/help — помощь"
)

WELCOME = (
    "Привет! 👋\n\n"
    "Я собираю объявления о квартирах в Ташкенте сразу с трёх площадок — "
    "<b>OLX, Uybor и Realt24</b> — и присылаю уведомление, как только появится "
    "вариант под ваш фильтр.\n\n"
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
@router.message(F.text == "➕ Новое уведомление")
async def cmd_new(msg: Message, state: FSMContext) -> None:
    await _begin_new_alert(msg, msg.from_user, state)


@router.callback_query(F.data.startswith("edit:"))
async def on_edit(cb: CallbackQuery, state: FSMContext) -> None:
    alert_id = int(cb.data.split(":", 1)[1])
    user_id = _ensure_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
    with SessionLocal() as db:
        alert = db.get(Alert, alert_id)
        if alert is None or alert.user_id != user_id:
            await cb.answer("Не нашёл уведомление.", show_alert=True)
            return
        districts = set((alert.districts or "").split(",")) - {""}
        rooms = {int(r) for r in (alert.rooms or "").split(",") if r}
        prefill = dict(
            editing_id=alert_id,
            districts=districts,
            rooms=rooms,
            price_min=alert.price_min,
            price_max=alert.price_max,
            area_min=alert.area_min,
            area_max=alert.area_max,
            floor_min=alert.floor_min,
            floor_max=alert.floor_max,
            discount_min=alert.discount_min,
        )

    await state.clear()
    await state.set_state(NewAlert.districts)
    await state.update_data(**prefill)
    await cb.message.answer(
        "✏️ Меняем фильтр. Шаг 1/6. Выберите районы (можно несколько):",
        reply_markup=districts_keyboard(districts),
    )
    await cb.answer()


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
            "Шаг 3/7. Цена (USD). Сначала выберите минимум (<b>от</b>):",
            reply_markup=price_from_keyboard(),
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


# ---------- Шаг 3: цена «от» → «до» ----------

@router.callback_query(NewAlert.price, F.data.startswith("pmin:"))
async def on_price_min(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    if payload == "any":
        await state.update_data(price_min=None, price_min_idx=None)
        idx = None
    else:
        idx = int(payload)
        await state.update_data(price_min=float(PRICE_VALUES[idx]), price_min_idx=idx)
    await cb.message.edit_text(
        "Шаг 3/7. Теперь максимум цены (<b>до</b>):",
        reply_markup=price_to_keyboard(idx),
    )
    await cb.answer()


@router.callback_query(NewAlert.price, F.data.startswith("pmax:"))
async def on_price_max(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    if payload == "any":
        await state.update_data(price_max=None)
    else:
        await state.update_data(price_max=float(PRICE_VALUES[int(payload)]))
    await state.set_state(NewAlert.area)
    await cb.message.edit_text(
        "Шаг 4/7. Площадь, м². Сначала минимум (<b>от</b>):",
        reply_markup=area_from_keyboard(),
    )
    await cb.answer()


# ---------- Шаг 4: площадь «от» → «до» ----------

@router.callback_query(NewAlert.area, F.data.startswith("amin:"))
async def on_area_min(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    if payload == "any":
        await state.update_data(area_min=None)
        idx = None
    else:
        idx = int(payload)
        await state.update_data(area_min=float(AREA_VALUES[idx]))
    await cb.message.edit_text(
        "Шаг 4/7. Теперь максимум площади (<b>до</b>):",
        reply_markup=area_to_keyboard(idx),
    )
    await cb.answer()


@router.callback_query(NewAlert.area, F.data.startswith("amax:"))
async def on_area_max(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    if payload == "any":
        await state.update_data(area_max=None)
    else:
        await state.update_data(area_max=float(AREA_VALUES[int(payload)]))
    await state.set_state(NewAlert.floor)
    await cb.message.edit_text(
        "Шаг 5/7. Этаж. Сначала минимум (<b>от</b>):",
        reply_markup=floor_from_keyboard(),
    )
    await cb.answer()


# ---------- Шаг 5: этаж «от» → «до» ----------

@router.callback_query(NewAlert.floor, F.data.startswith("fmin:"))
async def on_floor_min(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    if payload == "any":
        await state.update_data(floor_min=None)
        idx = None
    else:
        idx = int(payload)
        await state.update_data(floor_min=FLOOR_VALUES[idx])
    await cb.message.edit_text(
        "Шаг 5/7. Теперь максимум этажа (<b>до</b>):",
        reply_markup=floor_to_keyboard(idx),
    )
    await cb.answer()


@router.callback_query(NewAlert.floor, F.data.startswith("fmax:"))
async def on_floor_max(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    if payload == "any":
        await state.update_data(floor_max=None)
    else:
        await state.update_data(floor_max=FLOOR_VALUES[int(payload)])
    await state.set_state(NewAlert.discount)
    await cb.message.edit_text(
        "Шаг 6/7. Насколько ниже рынка должна быть цена?",
        reply_markup=discount_keyboard(),
    )
    await cb.answer()


# ---------- Шаг 6: скидка к рынку (пресеты) ----------

@router.callback_query(NewAlert.discount, F.data.startswith("disc:"))
async def on_discount(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    if payload == "any":
        await state.update_data(discount_min=None)
    else:
        _, frac = DISCOUNT_PRESETS[int(payload)]
        await state.update_data(discount_min=frac)
    await state.set_state(NewAlert.name)
    await cb.message.edit_text(
        "Шаг 7/7. Как назвать этот фильтр? Напишите любое короткое имя "
        "(например «3-комн. Юнусабад»)."
    )
    await cb.answer()


@router.message(NewAlert.name)
async def set_name(msg: Message, state: FSMContext) -> None:
    name = (msg.text or "").strip()[:80] or "Без имени"
    data = await state.get_data()
    user_id = _ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)

    districts = sorted(data.get("districts") or set())
    rooms = sorted(int(r) for r in (data.get("rooms") or set()))
    editing_id = data.get("editing_id")

    fields = dict(
        name=name,
        districts=",".join(districts) if districts else None,
        rooms=",".join(str(r) for r in rooms) if rooms else None,
        price_min=data.get("price_min"),
        price_max=data.get("price_max"),
        area_min=data.get("area_min"),
        area_max=data.get("area_max"),
        floor_min=data.get("floor_min"),
        floor_max=data.get("floor_max"),
        discount_min=data.get("discount_min"),
    )

    with SessionLocal() as db:
        if editing_id is not None:
            alert = db.get(Alert, editing_id)
            if alert is None or alert.user_id != user_id:
                await state.clear()
                await msg.answer("Не нашёл уведомление для изменения.", reply_markup=main_menu())
                return
            for key, value in fields.items():
                setattr(alert, key, value)
        else:
            alert = Alert(user_id=user_id, is_active=True, created_at=datetime.utcnow(), **fields)
            db.add(alert)
        db.commit()
        db.refresh(alert)
        summary = describe_alert(alert)

    await state.clear()
    verb = "обновлено" if editing_id is not None else "создано"
    await msg.answer(
        f"✅ Уведомление <b>«{name}»</b> {verb}.\n\n{summary}\n\n"
        "Теперь я пришлю сообщение, как только появится подходящая квартира.",
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
            "Уведомлений пока нет. Нажмите «➕ Новое уведомление», чтобы создать первое.",
            reply_markup=main_menu(),
        )
        return

    for a in alerts:
        status = "🟢 активно" if a.is_active else "⏸ на паузе"
        text = f"<b>{a.name}</b> · {status}\n\n{describe_alert(a)}"
        await msg.answer(text, reply_markup=alert_actions(a.id, a.is_active))


@router.message(Command("list"))
@router.message(F.text == "📋 Мои уведомления")
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
            await cb.answer("Не нашёл уведомление.", show_alert=True)
            return
        alert.is_active = not alert.is_active
        db.commit()
        new_state = alert.is_active
        name = alert.name
        summary = describe_alert(alert)

    status = "🟢 активно" if new_state else "⏸ на паузе"
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
            await cb.answer("Не нашёл уведомление.", show_alert=True)
            return
        db.delete(alert)
        db.commit()

    await cb.message.edit_text("🗑 Уведомление удалено.")
    await cb.answer()
