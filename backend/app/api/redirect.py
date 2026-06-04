"""GET /r/{token} — трекаем клик по алёрту и редиректим на источник.

Ссылка в уведомлении ведёт сюда (а не напрямую на OLX/Uybor), чтобы мерить
CTR. Кладётся в inline-кнопку — Telegram не префетчит кнопки, поэтому клик
здесь = живой человек, а не превью-бот. Любой сбой/левый токен → редирект на
главную, чтобы юзер никогда не упёрся в тупик.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AlertSend, Listing
from app.services.click_token import unsign_send

router = APIRouter(tags=["redirect"])

HOME = "https://uyradar.uz/"


@router.get("/r/{token}", include_in_schema=False)
def track_click(token: str, db: Session = Depends(get_db)) -> RedirectResponse:
    send_id = unsign_send(token)
    if send_id is None:
        return RedirectResponse(HOME, status_code=302)

    send = db.get(AlertSend, send_id)
    if send is None:
        return RedirectResponse(HOME, status_code=302)

    # Уникальный клик: фиксируем только первый раз.
    if send.clicked_at is None:
        send.clicked_at = datetime.utcnow()
        db.commit()

    listing = db.get(Listing, send.listing_id) if send.listing_id else None
    target = listing.url if listing and listing.url else HOME
    return RedirectResponse(target, status_code=302)
