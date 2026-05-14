from __future__ import annotations

from datetime import datetime, timedelta

from app.auth.dependencies import resolve_user_plan
from app.core.plans import get_limits_for_plan
from app.models import Subscription, User


def test_limits_per_plan():
    assert get_limits_for_plan("free")["listing_delay_hours"] == 24
    assert get_limits_for_plan("free")["daily_listings_limit"] == 15
    assert get_limits_for_plan("pro")["listing_delay_hours"] == 0
    assert get_limits_for_plan("pro")["analytics_level"] == "basic"
    assert get_limits_for_plan("agent")["max_saved_filters"] is None
    assert get_limits_for_plan("agent")["api_access"] is True
    # unknown plan falls back to free
    assert get_limits_for_plan("nonsense") == get_limits_for_plan("free")


def test_anonymous_limits_endpoint(client):
    body = client.get("/auth/limits").json()
    assert body["plan"] == "free"
    assert body["limits"]["export_enabled"] is False


def _make_user(db, telegram_id=4242):
    user = User(telegram_id=telegram_id)
    db.add(user)
    db.flush()
    return user


def test_resolve_plan_no_subscription_is_free(db_session):
    user = _make_user(db_session)
    assert resolve_user_plan(db_session, user) == "free"
    assert resolve_user_plan(db_session, None) == "free"


def test_resolve_plan_active_subscription(db_session):
    user = _make_user(db_session, 4243)
    db_session.add(Subscription(user_id=user.id, plan="pro", status="active"))
    db_session.flush()
    assert resolve_user_plan(db_session, user) == "pro"


def test_resolve_plan_expired_subscription_is_free(db_session):
    user = _make_user(db_session, 4244)
    db_session.add(
        Subscription(
            user_id=user.id,
            plan="agent",
            status="active",
            expires_at=datetime.utcnow() - timedelta(days=1),
        )
    )
    db_session.flush()
    assert resolve_user_plan(db_session, user) == "free"
