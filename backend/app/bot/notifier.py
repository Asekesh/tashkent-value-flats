from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import func, select

from app.bot.bot import build_bot
from app.bot.matcher import alert_matches_listing
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Alert, Listing, ListingEvent, User

logger = logging.getLogger(__name__)

# Сколько новых листингов за один тик максимум разбираем, чтобы не висеть
# минутами после большого скрейпа и не словить flood-wait у Телеграма.
MAX_EVENTS_PER_TICK = 200


async def notifier_loop(poll_interval_seconds: int = 30) -> None:
    """Каждые N секунд: смотрим новые ListingEvent(first_seen), для каждого
    подбираем активные алёрты и шлём чаты пользователям. Курсор хранится
    в памяти — на старте берём текущий max(id) события, чтобы не спамить
    бэклогом при деплое.
    """
    bot = build_bot()
    if bot is None:
        return

    cursor = _initial_cursor()
    logger.info("notifier_loop started cursor=%s", cursor)

    while True:
        try:
            cursor = await asyncio.to_thread(_process_batch, cursor)
        except Exception:
            logger.exception("notifier tick failed")
        await asyncio.sleep(poll_interval_seconds)


def _initial_cursor() -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.coalesce(func.max(ListingEvent.id), 0))) or 0)


def _process_batch(cursor: int) -> int:
    """Sync функция, выполняемая в thread'е: собирает события и
    рассылает уведомления через httpx (через aiogram.Bot нельзя из чужого
    цикла, поэтому ходим напрямую в Bot API).
    """
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        return cursor

    with SessionLocal() as db:
        events = db.scalars(
            select(ListingEvent)
            .where(ListingEvent.id > cursor, ListingEvent.event_type == "first_seen")
            .order_by(ListingEvent.id.asc())
            .limit(MAX_EVENTS_PER_TICK)
        ).all()
        if not events:
            return cursor

        listing_ids = [e.listing_id for e in events]
        listings = {
            l.id: l for l in db.scalars(select(Listing).where(Listing.id.in_(listing_ids))).all()
        }
        alerts_by_user: dict[int, list[Alert]] = {}
        alerts = db.scalars(select(Alert).where(Alert.is_active.is_(True))).all()
        users = {
            u.id: u for u in db.scalars(
                select(User).where(User.id.in_({a.user_id for a in alerts}))
            ).all()
        }
        for a in alerts:
            alerts_by_user.setdefault(a.user_id, []).append(a)

        # Дедуп: один листинг → один пуш одному пользователю даже если
        # под него подходит несколько алёртов (берём первый совпавший).
        to_send: list[tuple[int, Listing, Alert]] = []
        for ev in events:
            listing = listings.get(ev.listing_id)
            if listing is None or listing.status != "active":
                continue
            if (listing.price_usd or 0) < settings.min_listing_price_usd:
                continue
            for user_id, user_alerts in alerts_by_user.items():
                user = users.get(user_id)
                if user is None or not user.is_active:
                    continue
                for alert in user_alerts:
                    if alert_matches_listing(alert, listing):
                        to_send.append((user.telegram_id, listing, alert))
                        break  # один пуш на пользователя на листинг

        last_id = events[-1].id

    # Шлём СИНХРОННЫМ httpx — нет конфликта с aiogram loop'ом.
    if to_send:
        import httpx
        with httpx.Client(timeout=10.0) as client:
            for chat_id, listing, alert in to_send:
                _send_listing_sync(client, token, chat_id, listing, alert)
        with SessionLocal() as db:
            now = datetime.utcnow()
            for _, _, alert in to_send:
                a = db.get(Alert, alert.id)
                if a is not None:
                    a.last_notified_at = now
            db.commit()

    return last_id


def _send_listing_sync(client, token: str, chat_id: int, listing: Listing, alert: Alert) -> None:
    short_district = (listing.district or "").replace("ский район", "").replace(" район", "")
    title = (listing.title or "")[:120]
    price = f"${int(listing.price_usd or 0):,}".replace(",", " ")
    ppm = int(listing.price_per_m2_usd or 0)
    discount = ""
    if listing.discount_percent is not None and listing.discount_percent > 0:
        discount = f"\n🎯 <b>{int(listing.discount_percent * 100)}% ниже рынка</b>"

    text = (
        f"🆕 <b>{alert.name}</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"💰 {price} · 📐 {ppm}$/м² · 📏 {int(listing.area_m2 or 0)} м² · 🛏 {listing.rooms}к\n"
        f"📍 {short_district}"
        f"{discount}\n\n"
        f"<a href=\"{listing.url}\">Открыть на источнике →</a>"
    )

    try:
        resp = client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
        )
        if resp.status_code == 403:
            # Пользователь заблокировал бота — деактивируем алёрты.
            with SessionLocal() as db:
                user = db.scalar(select(User).where(User.telegram_id == chat_id))
                if user is not None:
                    db.execute(
                        Alert.__table__.update()
                        .where(Alert.user_id == user.id)
                        .values(is_active=False)
                    )
                    db.commit()
        elif resp.status_code == 429:
            retry = resp.json().get("parameters", {}).get("retry_after", 1)
            import time as _t
            _t.sleep(retry + 1)
    except Exception:
        logger.exception("send to %s failed", chat_id)
