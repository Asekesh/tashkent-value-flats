from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ErrorEvent, Message
from sqlalchemy import func, select

from app.bot.keyboards import (
    AREA_VALUES,
    DISCOUNT_PRESETS,
    FLOOR_VALUES,
    price_values,
    alert_actions,
    area_from_keyboard,
    area_to_keyboard,
    commission_keyboard,
    deal_type_keyboard,
    discount_keyboard,
    districts_keyboard,
    feedback_kind_keyboard,
    floor_from_keyboard,
    floor_to_keyboard,
    lang_keyboard,
    main_menu,
    price_from_keyboard,
    price_to_keyboard,
    rooms_keyboard,
    start_inline,
)
from app.bot.i18n import normalize_lang, pick_lang, t
from app.bot.matcher import describe_alert
from app.bot.states import Feedback, NewAlert
from app.auth.dependencies import resolve_user_plan
from app.core.plans import get_limits_for_plan
from app.db.session import SessionLocal
from app.models import Alert, Feedback as FeedbackModel, LimitEvent, User
from app.services.activity import mark_active
from app.services.feedback_notify import notify_admins_new_feedback
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


_SOURCE_RE = re.compile(r"[^A-Za-z0-9_-]")


def _clean_source(raw: Optional[str]) -> Optional[str]:
    """Deep-link payload → безопасный токен источника (Telegram допускает
    [A-Za-z0-9_-], ≤64). Пустое/мусор → None."""
    if not raw:
        return None
    cleaned = _SOURCE_RE.sub("", raw)[:64]
    return cleaned or None


def _ensure_user(
    tg_id: int,
    username: Optional[str],
    first_name: Optional[str],
    source: Optional[str] = None,
    language_code: Optional[str] = None,
) -> tuple[int, str]:
    """Создаёт/обновляет пользователя, возвращает (id, lang).

    Язык ставится один раз при создании (по Telegram language_code) и дальше
    не перетирается — пользователь мог сменить его вручную кнопкой в меню.
    """
    now = datetime.utcnow()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_id == tg_id))
        if user is None:
            user = User(
                telegram_id=tg_id,
                username=username,
                first_name=first_name,
                source=source,
                last_seen_at=now,
                lang=pick_lang(language_code),
            )
            db.add(user)
        else:
            # Сенсор активности: пишем на каждое касание (DAU/WAU/отвал).
            user.last_seen_at = now
            # first-touch: источник проставляем только если ещё пуст.
            if source and not user.source:
                user.source = source
        db.flush()  # нужен user.id для отметки активности
        mark_active(db, user.id, now)
        db.commit()
        db.refresh(user)
        return user.id, normalize_lang(user.lang)


def _set_lang(tg_id: int, lang: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_id == tg_id))
        if user is not None:
            user.lang = normalize_lang(lang)
            db.commit()


# ---------- /start, /help, menu buttons ----------

@router.message(CommandStart())
async def cmd_start(msg: Message, command: CommandObject) -> None:
    # Deep-link t.me/uyradaruz_bot?start=<источник> — ловим payload (атрибуция).
    source = _clean_source(command.args)
    _, lang = _ensure_user(
        msg.from_user.id,
        msg.from_user.username,
        msg.from_user.first_name,
        source=source,
        language_code=msg.from_user.language_code,
    )
    # сначала ставим reply-клавиатуру, затем — крупные inline-кнопки для новичков
    await msg.answer(t("welcome", lang), reply_markup=main_menu(lang))
    await msg.answer(t("choose_action", lang), reply_markup=start_inline(lang))


@router.message(Command("help"))
@router.message(F.text.in_({"ℹ️ Помощь", "ℹ️ Yordam"}))
async def cmd_help(msg: Message) -> None:
    _, lang = _ensure_user(
        msg.from_user.id, msg.from_user.username, msg.from_user.first_name,
        language_code=msg.from_user.language_code,
    )
    await msg.answer(t("help", lang), reply_markup=main_menu(lang))


# ---------- Смена языка ----------

@router.message(F.text == "🌐 Til / Язык")
async def cmd_lang(msg: Message) -> None:
    _, lang = _ensure_user(
        msg.from_user.id, msg.from_user.username, msg.from_user.first_name,
        language_code=msg.from_user.language_code,
    )
    await msg.answer(t("lang_choose", lang), reply_markup=lang_keyboard())


@router.callback_query(F.data.startswith("setlang:"))
async def on_set_lang(cb: CallbackQuery) -> None:
    lang = normalize_lang(cb.data.split(":", 1)[1])
    _ensure_user(
        cb.from_user.id, cb.from_user.username, cb.from_user.first_name,
        language_code=cb.from_user.language_code,
    )
    _set_lang(cb.from_user.id, lang)
    await cb.message.answer(t("lang_done", lang), reply_markup=main_menu(lang))
    await cb.answer()


# ---------- Обратная связь ----------

async def _begin_feedback(msg: Message, lang: str, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Feedback.kind)
    await state.update_data(lang=lang)
    await msg.answer(
        t("feedback_intro", lang),
        reply_markup=feedback_kind_keyboard(lang),
    )


@router.message(F.text.in_({"✍️ Обратная связь", "✍️ Fikr-mulohaza"}))
async def cmd_feedback(msg: Message, state: FSMContext) -> None:
    _, lang = _ensure_user(
        msg.from_user.id, msg.from_user.username, msg.from_user.first_name,
        language_code=msg.from_user.language_code,
    )
    await _begin_feedback(msg, lang, state)


@router.callback_query(F.data == "start:feedback")
async def start_feedback(cb: CallbackQuery, state: FSMContext) -> None:
    _, lang = _ensure_user(
        cb.from_user.id, cb.from_user.username, cb.from_user.first_name,
        language_code=cb.from_user.language_code,
    )
    await _begin_feedback(cb.message, lang, state)
    await cb.answer()


@router.callback_query(Feedback.kind, F.data.startswith("fb:"))
async def on_feedback_kind(cb: CallbackQuery, state: FSMContext) -> None:
    kind = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    await state.update_data(kind=kind)
    await state.set_state(Feedback.text)
    prompt = t("feedback_bug", lang) if kind == "bug" else t("feedback_feature", lang)
    await cb.message.edit_text(prompt)
    await cb.answer()


@router.message(Feedback.text)
async def on_feedback_text(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    text = (msg.text or "").strip()[:2000]
    if not text:
        await msg.answer(t("feedback_empty", lang))
        return
    kind = data.get("kind") or "bug"
    user_id, _ = _ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    contact = msg.from_user.username or msg.from_user.first_name or f"id{msg.from_user.id}"

    with SessionLocal() as db:
        db.add(FeedbackModel(
            user_id=user_id,
            kind=kind,
            message=text,
            source="bot",
            contact=contact,
        ))
        db.commit()

    notify_admins_new_feedback(kind, text, contact, "bot")
    await state.clear()
    await msg.answer(
        t("feedback_thanks", lang),
        reply_markup=main_menu(lang),
    )


# ---------- /new flow ----------

async def _begin_new_alert(msg: Message, user, state: FSMContext) -> None:
    _, lang = _ensure_user(
        user.id, user.username, user.first_name,
        language_code=getattr(user, "language_code", None),
    )
    await state.clear()
    await state.set_state(NewAlert.deal_type)
    await state.update_data(districts=set(), deal_type="sale", lang=lang)
    await msg.answer(
        t("step_deal_type", lang),
        reply_markup=deal_type_keyboard("sale", lang),
    )


@router.message(Command("new"))
@router.message(F.text.in_({"➕ Новое уведомление", "➕ Yangi bildirishnoma"}))
async def cmd_new(msg: Message, state: FSMContext) -> None:
    await _begin_new_alert(msg, msg.from_user, state)


@router.callback_query(F.data.startswith("edit:"))
async def on_edit(cb: CallbackQuery, state: FSMContext) -> None:
    alert_id = int(cb.data.split(":", 1)[1])
    user_id, lang = _ensure_user(
        cb.from_user.id, cb.from_user.username, cb.from_user.first_name,
        language_code=cb.from_user.language_code,
    )
    with SessionLocal() as db:
        alert = db.get(Alert, alert_id)
        if alert is None or alert.user_id != user_id:
            await cb.answer(t("not_found", lang), show_alert=True)
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
            deal_type=alert.deal_type,
            no_commission=alert.no_commission,
        )

    await state.clear()
    await state.set_state(NewAlert.districts)
    await state.update_data(**prefill, lang=lang)
    await cb.message.answer(
        t("step_districts_edit", lang),
        reply_markup=districts_keyboard(districts, lang),
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
    _, lang = _ensure_user(
        cb.from_user.id, cb.from_user.username, cb.from_user.first_name,
        language_code=cb.from_user.language_code,
    )
    await cb.message.answer(t("help", lang), reply_markup=main_menu(lang))
    await cb.answer()


@router.callback_query(NewAlert.deal_type, F.data.startswith("deal:"))
async def on_deal_type(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    if payload == "done":
        await state.set_state(NewAlert.districts)
        await cb.message.edit_text(
            t("step_districts", lang),
            reply_markup=districts_keyboard(set(data.get("districts") or set()), lang),
        )
        await cb.answer()
        return
    # payload = sale | rent — переключаем галочку
    await state.update_data(deal_type=payload)
    await cb.message.edit_reply_markup(reply_markup=deal_type_keyboard(payload, lang))
    await cb.answer()


@router.callback_query(NewAlert.districts, F.data.startswith("dist:"))
async def on_district(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    selected: set[str] = set(data.get("districts") or set())

    if payload == "any":
        selected.clear()
        await state.update_data(districts=selected)
        await cb.message.edit_reply_markup(reply_markup=districts_keyboard(selected, lang))
        await cb.answer(t("reset_district", lang))
        return

    if payload == "done":
        await state.set_state(NewAlert.rooms)
        await state.update_data(rooms=set())
        await cb.message.edit_text(
            t("step_rooms", lang),
            reply_markup=rooms_keyboard(set(), lang),
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
    await cb.message.edit_reply_markup(reply_markup=districts_keyboard(selected, lang))
    await cb.answer()


@router.callback_query(NewAlert.rooms, F.data.startswith("rooms:"))
async def on_rooms(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    selected: set[int] = set(data.get("rooms") or set())

    if payload == "any":
        selected.clear()
        await state.update_data(rooms=selected)
        await cb.message.edit_reply_markup(reply_markup=rooms_keyboard(selected, lang))
        await cb.answer(t("reset_any", lang))
        return

    if payload == "done":
        await state.set_state(NewAlert.price)
        await cb.message.edit_text(
            t("step_price_min", lang),
            reply_markup=price_from_keyboard(lang, data.get("deal_type", "sale")),
        )
        await cb.answer()
        return

    n = int(payload)
    if n in selected:
        selected.remove(n)
    else:
        selected.add(n)
    await state.update_data(rooms=selected)
    await cb.message.edit_reply_markup(reply_markup=rooms_keyboard(selected, lang))
    await cb.answer()


# ---------- Шаг 3: цена «от» → «до» ----------

@router.callback_query(NewAlert.price, F.data.startswith("pmin:"))
async def on_price_min(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    if payload == "any":
        await state.update_data(price_min=None, price_min_idx=None)
        idx = None
    else:
        idx = int(payload)
        prices = price_values(data.get("deal_type", "sale"))
        await state.update_data(price_min=float(prices[idx]), price_min_idx=idx)
    await cb.message.edit_text(
        t("step_price_max", lang),
        reply_markup=price_to_keyboard(idx, lang, data.get("deal_type", "sale")),
    )
    await cb.answer()


@router.callback_query(NewAlert.price, F.data.startswith("pmax:"))
async def on_price_max(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    if payload == "any":
        await state.update_data(price_max=None)
    else:
        prices = price_values(data.get("deal_type", "sale"))
        await state.update_data(price_max=float(prices[int(payload)]))
    await state.set_state(NewAlert.area)
    await cb.message.edit_text(
        t("step_area_min", lang),
        reply_markup=area_from_keyboard(lang),
    )
    await cb.answer()


# ---------- Шаг 4: площадь «от» → «до» ----------

@router.callback_query(NewAlert.area, F.data.startswith("amin:"))
async def on_area_min(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    if payload == "any":
        await state.update_data(area_min=None)
        idx = None
    else:
        idx = int(payload)
        await state.update_data(area_min=float(AREA_VALUES[idx]))
    await cb.message.edit_text(
        t("step_area_max", lang),
        reply_markup=area_to_keyboard(idx, lang),
    )
    await cb.answer()


@router.callback_query(NewAlert.area, F.data.startswith("amax:"))
async def on_area_max(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    if payload == "any":
        await state.update_data(area_max=None)
    else:
        await state.update_data(area_max=float(AREA_VALUES[int(payload)]))
    await state.set_state(NewAlert.floor)
    await cb.message.edit_text(
        t("step_floor_min", lang),
        reply_markup=floor_from_keyboard(lang),
    )
    await cb.answer()


# ---------- Шаг 5: этаж «от» → «до» ----------

@router.callback_query(NewAlert.floor, F.data.startswith("fmin:"))
async def on_floor_min(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    if payload == "any":
        await state.update_data(floor_min=None)
        idx = None
    else:
        idx = int(payload)
        await state.update_data(floor_min=FLOOR_VALUES[idx])
    await cb.message.edit_text(
        t("step_floor_max", lang),
        reply_markup=floor_to_keyboard(idx, lang),
    )
    await cb.answer()


@router.callback_query(NewAlert.floor, F.data.startswith("fmax:"))
async def on_floor_max(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    if payload == "any":
        await state.update_data(floor_max=None)
    else:
        await state.update_data(floor_max=FLOOR_VALUES[int(payload)])
    if data.get("deal_type") == "rent":
        await state.set_state(NewAlert.commission)
        await cb.message.edit_text(
            t("step_commission", lang),
            reply_markup=commission_keyboard(lang),
        )
    else:
        await state.set_state(NewAlert.discount)
        await cb.message.edit_text(
            t("step_discount", lang),
            reply_markup=discount_keyboard(lang),
        )
    await cb.answer()


# ---------- Шаг 6: скидка к рынку (пресеты) ----------

@router.callback_query(NewAlert.discount, F.data.startswith("disc:"))
async def on_discount(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    if payload == "any":
        await state.update_data(discount_min=None)
    else:
        _, frac = DISCOUNT_PRESETS[int(payload)]
        await state.update_data(discount_min=frac)
    await state.set_state(NewAlert.name)
    await cb.message.edit_text(t("step_name", lang))
    await cb.answer()


@router.callback_query(NewAlert.commission, F.data.startswith("comm:"))
async def on_commission(cb: CallbackQuery, state: FSMContext) -> None:
    payload = cb.data.split(":", 1)[1]
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    await state.update_data(no_commission=True if payload == "yes" else None)
    await state.set_state(NewAlert.name)
    await cb.message.edit_text(t("step_name", lang))
    await cb.answer()


@router.message(NewAlert.name)
async def set_name(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = normalize_lang(data.get("lang"))
    name = (msg.text or "").strip()[:80] or t("noname", lang)
    user_id, _ = _ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)

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
        deal_type=data.get("deal_type", "sale"),
        no_commission=data.get("no_commission"),
    )

    with SessionLocal() as db:
        if editing_id is not None:
            alert = db.get(Alert, editing_id)
            if alert is None or alert.user_id != user_id:
                await state.clear()
                await msg.answer(t("not_found_edit", lang), reply_markup=main_menu(lang))
                return
            for key, value in fields.items():
                setattr(alert, key, value)
        else:
            # Лид-сигнал на платник: фиксируем (не блокируем), когда free-юзер
            # создаёт алёрт сверх лимита тарифа.
            existing = (
                db.scalar(select(func.count(Alert.id)).where(Alert.user_id == user_id))
                or 0
            )
            plan = resolve_user_plan(db, db.get(User, user_id))
            cap = get_limits_for_plan(plan).get("max_saved_filters")
            if cap is not None and existing >= cap:
                db.add(
                    LimitEvent(
                        user_id=user_id,
                        event_type="alert_cap",
                        plan=plan,
                        detail=f"{existing + 1}-й алёрт при лимите {cap}",
                    )
                )
            alert = Alert(user_id=user_id, is_active=True, created_at=datetime.utcnow(), **fields)
            db.add(alert)
        db.commit()
        db.refresh(alert)
        summary = describe_alert(alert, lang)

    await state.clear()
    verb = t("verb_updated", lang) if editing_id is not None else t("verb_created", lang)
    await msg.answer(
        t("saved", lang, name=name, verb=verb, summary=summary),
        reply_markup=main_menu(lang),
    )


# ---------- /list ----------

async def _send_alerts(msg: Message, user) -> None:
    user_id, lang = _ensure_user(
        user.id, user.username, user.first_name,
        language_code=getattr(user, "language_code", None),
    )
    with SessionLocal() as db:
        alerts = db.scalars(
            select(Alert).where(Alert.user_id == user_id).order_by(Alert.id.desc())
        ).all()

    if not alerts:
        await msg.answer(
            t("no_alerts", lang),
            reply_markup=main_menu(lang),
        )
        return

    for a in alerts:
        status = t("status_active", lang) if a.is_active else t("status_paused", lang)
        text = f"<b>{a.name}</b> · {status}\n\n{describe_alert(a, lang)}"
        await msg.answer(text, reply_markup=alert_actions(a.id, a.is_active, lang))


@router.message(Command("list"))
@router.message(F.text.in_({"📋 Мои уведомления", "📋 Mening bildirishnomalarim"}))
async def cmd_list(msg: Message) -> None:
    await _send_alerts(msg, msg.from_user)


@router.callback_query(F.data.startswith("toggle:"))
async def on_toggle(cb: CallbackQuery) -> None:
    alert_id = int(cb.data.split(":", 1)[1])
    user_id, lang = _ensure_user(
        cb.from_user.id, cb.from_user.username, cb.from_user.first_name,
        language_code=cb.from_user.language_code,
    )
    with SessionLocal() as db:
        alert = db.get(Alert, alert_id)
        if alert is None or alert.user_id != user_id:
            await cb.answer(t("not_found", lang), show_alert=True)
            return
        alert.is_active = not alert.is_active
        db.commit()
        new_state = alert.is_active
        name = alert.name
        summary = describe_alert(alert, lang)

    status = t("status_active", lang) if new_state else t("status_paused", lang)
    await cb.message.edit_text(
        f"<b>{name}</b> · {status}\n\n{summary}",
        reply_markup=alert_actions(alert_id, new_state, lang),
    )
    await cb.answer(t("done", lang))


@router.callback_query(F.data.startswith("del:"))
async def on_delete(cb: CallbackQuery) -> None:
    alert_id = int(cb.data.split(":", 1)[1])
    user_id, lang = _ensure_user(
        cb.from_user.id, cb.from_user.username, cb.from_user.first_name,
        language_code=cb.from_user.language_code,
    )
    with SessionLocal() as db:
        alert = db.get(Alert, alert_id)
        if alert is None or alert.user_id != user_id:
            await cb.answer(t("not_found", lang), show_alert=True)
            return
        db.delete(alert)
        db.commit()

    await cb.message.edit_text(t("deleted", lang))
    await cb.answer()
