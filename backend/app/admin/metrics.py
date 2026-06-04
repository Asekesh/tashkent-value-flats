"""Read-only aggregate queries for the admin dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Alert, AlertSend, LoginEvent, ScrapeRun, Subscription, User


def _active_subscription_filter():
    now = datetime.utcnow()
    return [
        Subscription.status == "active",
        or_(Subscription.expires_at.is_(None), Subscription.expires_at >= now),
    ]


def parser_health(db: Session) -> list[dict[str, Any]]:
    """Здоровье парсеров по источникам — детектор тихой смерти.

    status='success' сам по себе не гарант: сломанный селектор даёт успешный
    run, нашедший 0. Поэтому health='empty', когда последний успешный прогон
    извлёк 0 (new+updated) — парсил, но ничего не достал. Если же давно нет
    успешного прогона — 'stale'; последний упал — 'error'; успехов нет —
    'down'. Данные уже лежат в scrape_runs, миграций не нужно.
    """
    now = datetime.utcnow()
    day_start = datetime(now.year, now.month, now.day)
    stale_after = timedelta(minutes=max(get_settings().scrape_interval_minutes * 8, 60))

    sources = [
        s
        for (s,) in db.execute(
            select(ScrapeRun.source).distinct().order_by(ScrapeRun.source)
        ).all()
    ]

    rows: list[dict[str, Any]] = []
    for src in sources:
        last_run = db.scalar(
            select(ScrapeRun)
            .where(ScrapeRun.source == src)
            .order_by(ScrapeRun.started_at.desc())
            .limit(1)
        )
        last_success = db.scalar(
            select(ScrapeRun)
            .where(ScrapeRun.source == src, ScrapeRun.status == "success")
            .order_by(ScrapeRun.finished_at.desc())
            .limit(1)
        )
        new_today = (
            db.scalar(
                select(func.coalesce(func.sum(ScrapeRun.new_count), 0)).where(
                    ScrapeRun.source == src,
                    ScrapeRun.status == "success",
                    ScrapeRun.finished_at >= day_start,
                )
            )
            or 0
        )
        last_success_at = last_success.finished_at if last_success else None
        last_found = (
            (last_success.new_count or 0) + (last_success.updated_count or 0)
            if last_success
            else 0
        )
        if last_success_at is None:
            health = "down"
        elif last_run is not None and last_run.status == "failed":
            health = "error"
        elif now - last_success_at > stale_after:
            health = "stale"
        elif last_found == 0:
            health = "empty"
        else:
            health = "ok"
        rows.append(
            {
                "source": src,
                "health": health,
                "last_success_age_h": (
                    round((now - last_success_at).total_seconds() / 3600, 1)
                    if last_success_at
                    else None
                ),
                "last_status": last_run.status if last_run else None,
                "last_found": int(last_found),
                "new_today": int(new_today),
            }
        )
    return rows


def ctr_stats(db: Session) -> dict[str, Any]:
    """CTR алёртов: отправлено → кликнуто. Главный сигнал «работает ли продукт».

    Клик считаем уникальный (clicked_at стоит/нет). Разрез по корзинам скидки
    (срез discount_snapshot на момент отправки) показывает, реально ли скидка к
    рынку гонит клики — это обратная связь под дисконт-алгоритм. by_discount
    берём за 30 дней для объёма; общий CTR — за 7.
    """
    now = datetime.utcnow()
    since7 = now - timedelta(days=7)

    sends_7d = (
        db.scalar(select(func.count(AlertSend.id)).where(AlertSend.sent_at >= since7)) or 0
    )
    clicks_7d = (
        db.scalar(
            select(func.count(AlertSend.id)).where(
                AlertSend.sent_at >= since7, AlertSend.clicked_at.isnot(None)
            )
        )
        or 0
    )
    ctr_7d = round(clicks_7d / sends_7d * 100, 1) if sends_7d else 0.0

    since30 = now - timedelta(days=30)
    buckets = [("< 10%", 0, 10), ("10–20%", 10, 20), ("20–30%", 20, 30), ("30%+", 30, 10_000)]
    by_discount: list[dict[str, Any]] = []
    for label, lo, hi in buckets:
        cond = [
            AlertSend.sent_at >= since30,
            AlertSend.discount_snapshot >= lo,
            AlertSend.discount_snapshot < hi,
        ]
        b_sends = db.scalar(select(func.count(AlertSend.id)).where(*cond)) or 0
        b_clicks = (
            db.scalar(
                select(func.count(AlertSend.id)).where(
                    *cond, AlertSend.clicked_at.isnot(None)
                )
            )
            or 0
        )
        by_discount.append(
            {
                "label": label,
                "sends": b_sends,
                "clicks": b_clicks,
                "ctr": round(b_clicks / b_sends * 100, 1) if b_sends else 0.0,
            }
        )

    return {
        "sends_7d": sends_7d,
        "clicks_7d": clicks_7d,
        "ctr_7d": ctr_7d,
        "by_discount": by_discount,
    }


def source_attribution(db: Session) -> list[dict[str, Any]]:
    """Канал привлечения → зарегано / стало активными / конверсия %.

    'Активный' = есть хотя бы один алёрт (та же дефиниция, что bot_users).
    source=NULL — legacy/органика (пришли до меток или через веб-логин без
    utm). Прямой ответ на «блогеры vs SMM»: где регистрации дешевле
    конвертятся в активных. Источник пишется first-touch в боте по
    deep-link ?start=<метка>.
    """
    registered = dict(
        db.execute(
            select(User.source, func.count(User.id)).group_by(User.source)
        ).all()
    )
    activated = dict(
        db.execute(
            select(User.source, func.count(func.distinct(User.id)))
            .join(Alert, Alert.user_id == User.id)
            .group_by(User.source)
        ).all()
    )
    rows: list[dict[str, Any]] = []
    for source, reg in registered.items():
        act = activated.get(source, 0)
        rows.append(
            {
                "source": source or "— без метки",
                "registered": reg,
                "activated": act,
                "conversion": round(act / reg * 100) if reg else 0,
            }
        )
    rows.sort(key=lambda r: r["registered"], reverse=True)
    return rows


def dashboard_metrics(db: Session) -> dict[str, Any]:
    now = datetime.utcnow()
    day_start = datetime(now.year, now.month, now.day)

    total_users = db.scalar(select(func.count(User.id))) or 0
    new_today = (
        db.scalar(select(func.count(User.id)).where(User.created_at >= day_start)) or 0
    )
    new_7d = (
        db.scalar(
            select(func.count(User.id)).where(User.created_at >= now - timedelta(days=7))
        )
        or 0
    )
    new_30d = (
        db.scalar(
            select(func.count(User.id)).where(User.created_at >= now - timedelta(days=30))
        )
        or 0
    )
    logins_7d = (
        db.scalar(
            select(func.count(LoginEvent.id)).where(
                LoginEvent.created_at >= now - timedelta(days=7)
            )
        )
        or 0
    )

    account_types = {"individual": 0, "agent": 0}
    for account_type, count in db.execute(
        select(User.account_type, func.count(User.id)).group_by(User.account_type)
    ).all():
        account_types[account_type] = count

    users_with_sub = (
        db.scalar(
            select(func.count(func.distinct(Subscription.user_id))).where(
                *_active_subscription_filter()
            )
        )
        or 0
    )
    plans = {"free": max(total_users - users_with_sub, 0), "pro": 0, "agent": 0}
    for plan, count in db.execute(
        select(Subscription.plan, func.count(func.distinct(Subscription.user_id)))
        .where(*_active_subscription_filter())
        .group_by(Subscription.plan)
    ).all():
        if plan == "free":
            plans["free"] += count
        else:
            plans[plan] = plans.get(plan, 0) + count

    # --- Бот: воронка по алёртам (алёрты создаются только в боте) ---
    # «Пользуются ботом» = есть хотя бы один алёрт; «активных» = есть хотя бы
    # один активный алёрт (по нему сейчас идут уведомления). Зарегистрировано
    # = total_users (таблица users общая с веб-логином, отдельного флага нет).
    bot_users = db.scalar(select(func.count(func.distinct(Alert.user_id)))) or 0
    bot_active_users = (
        db.scalar(
            select(func.count(func.distinct(Alert.user_id))).where(
                Alert.is_active.is_(True)
            )
        )
        or 0
    )
    total_alerts = db.scalar(select(func.count(Alert.id))) or 0
    active_alerts = (
        db.scalar(select(func.count(Alert.id)).where(Alert.is_active.is_(True))) or 0
    )

    # Registrations per day, last 30 days, gap-filled.
    raw_counts: dict[str, int] = {}
    for day, count in db.execute(
        select(func.date(User.created_at), func.count(User.id))
        .where(User.created_at >= now - timedelta(days=30))
        .group_by(func.date(User.created_at))
    ).all():
        raw_counts[str(day)] = count
    registrations = []
    for offset in range(29, -1, -1):
        day = (day_start - timedelta(days=offset)).date()
        registrations.append({"day": day.isoformat(), "count": raw_counts.get(day.isoformat(), 0)})
    max_reg = max((row["count"] for row in registrations), default=0)

    return {
        "total_users": total_users,
        "new_today": new_today,
        "new_7d": new_7d,
        "new_30d": new_30d,
        "logins_7d": logins_7d,
        "account_types": account_types,
        "plans": plans,
        "registrations": registrations,
        "registrations_max": max_reg,
        "bot_users": bot_users,
        "bot_active_users": bot_active_users,
        "total_alerts": total_alerts,
        "active_alerts": active_alerts,
        "parser_health": parser_health(db),
        "source_attribution": source_attribution(db),
        "ctr": ctr_stats(db),
    }


def active_plan_by_user(db: Session, user_ids: list[int]) -> dict[int, str]:
    """Map user_id -> effective plan for the given users (default 'free')."""
    if not user_ids:
        return {}
    result = {uid: "free" for uid in user_ids}
    rows = db.execute(
        select(Subscription.user_id, Subscription.plan, Subscription.created_at)
        .where(Subscription.user_id.in_(user_ids), *_active_subscription_filter())
        .order_by(Subscription.created_at.asc())
    ).all()
    for user_id, plan, _created in rows:
        result[user_id] = plan  # later (newer) rows win
    return result
