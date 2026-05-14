"""FastAPI dependencies for the auth layer.

Public pages must keep working without a session, so `get_current_user`
returns `None` instead of raising when there is no valid cookie.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import decode_session_token
from app.core.config import get_settings
from app.core.plans import DEFAULT_PLAN, get_limits_for_plan
from app.db.session import get_db
from app.models import Subscription, User


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    """Read the JWT session cookie and return the User, or None."""
    token = request.cookies.get(get_settings().jwt_cookie_name)
    if not token:
        return None
    payload = decode_session_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def require_admin(user: Optional[User] = Depends(get_current_user)) -> User:
    """Allow only authenticated admins; otherwise 403."""
    if user is None or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def get_account_type(user: User) -> str:
    """Account type of a user. Extension point for future plan logic."""
    return user.account_type


def resolve_user_plan(db: Session, user: Optional[User]) -> str:
    """Plan of the user's active, non-expired subscription, else 'free'.

    Anonymous users and users without a subscription are treated as free.
    """
    if user is None:
        return DEFAULT_PLAN
    subscription = db.scalar(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.created_at.desc())
    )
    if subscription is None:
        return DEFAULT_PLAN
    if subscription.expires_at is not None and subscription.expires_at < datetime.utcnow():
        return DEFAULT_PLAN
    return subscription.plan


def get_plan_limits(
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Tariff limits for the current user. Usable as a FastAPI dependency."""
    return get_limits_for_plan(resolve_user_plan(db, user))
