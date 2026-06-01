"""Обратная связь: приём тикетов (ошибки/пожелания) с сайта.

Модальное окно на фронте шлёт POST /api/feedback. Тикет сохраняется в БД
(виден в /admin/feedback) и админам уходит пинг в Telegram. Логин не
обязателен — анонимная отправка допускается (user_id=None).
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import Feedback, User
from app.services.feedback_notify import notify_admins_new_feedback

router = APIRouter(prefix="/api", tags=["feedback"])


class FeedbackIn(BaseModel):
    kind: Literal["bug", "feature"]
    message: str

    @field_validator("message")
    @classmethod
    def _trim(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("message is empty")
        return v[:2000]


def _contact_of(user: Optional[User]) -> Optional[str]:
    if user is None:
        return None
    return user.username or user.first_name or f"id{user.telegram_id}"


@router.post("/feedback")
def submit_feedback(
    payload: FeedbackIn,
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if len(payload.message) < 1 or len(payload.message) > 2000:
        raise HTTPException(status_code=400, detail="Invalid message length")

    contact = _contact_of(user)
    fb = Feedback(
        user_id=user.id if user else None,
        kind=payload.kind,
        message=payload.message,
        source="web",
        contact=contact,
    )
    db.add(fb)
    db.commit()

    notify_admins_new_feedback(payload.kind, payload.message, contact, "web")
    return {"ok": True}
