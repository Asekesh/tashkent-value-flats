"""FastAPI dependencies for the auth layer.

Public pages must keep working without a session, so `get_current_user`
returns `None` instead of raising when there is no valid cookie.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.security import decode_session_token
from app.core.config import get_settings
from app.db.session import get_db
from app.models import User


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
