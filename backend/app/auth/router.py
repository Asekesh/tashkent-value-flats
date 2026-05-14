"""Telegram Login Widget callback + session cookie management."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, resolve_user_plan
from app.auth.security import create_session_token, verify_telegram_auth
from app.core.plans import get_limits_for_plan
from app.core.config import get_settings
from app.db.session import get_db
from app.models import User
from app.services.users import get_or_create_user, record_login_event

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _set_session_cookie(response: RedirectResponse, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.jwt_cookie_name,
        value=token,
        max_age=settings.jwt_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


@router.get("/telegram/callback")
def telegram_callback(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    settings = get_settings()
    params = dict(request.query_params)

    if not verify_telegram_auth(params, settings.telegram_bot_token):
        raise HTTPException(status_code=403, detail="Invalid Telegram auth payload")

    user = get_or_create_user(db, params)
    record_login_event(db, user, _client_ip(request))
    db.commit()

    token = create_session_token(user.id, user.telegram_id, user.role)
    response = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(response, token)
    return response


@router.get("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(get_settings().jwt_cookie_name)
    return response


@router.get("/config")
def auth_config() -> dict:
    """Public bits the frontend needs to render the Telegram Login Widget."""
    return {"bot_username": get_settings().telegram_bot_username}


@router.get("/me")
def me(
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    plan = resolve_user_plan(db, user)
    base = {"plan": plan, "limits": get_limits_for_plan(plan)}
    if user is None:
        return {"authenticated": False, **base}
    return {
        "authenticated": True,
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "photo_url": user.photo_url,
        "role": user.role,
        "account_type": user.account_type,
        **base,
    }


@router.get("/limits")
def limits(
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Tariff limits for the current user — 'what is this user allowed to do'."""
    plan = resolve_user_plan(db, user)
    return {"plan": plan, "limits": get_limits_for_plan(plan)}
