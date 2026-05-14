"""Read-only aggregate queries for the admin dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import LoginEvent, Subscription, User


def _active_subscription_filter():
    now = datetime.utcnow()
    return [
        Subscription.status == "active",
        or_(Subscription.expires_at.is_(None), Subscription.expires_at >= now),
    ]


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
