"""GET /r/{token} — трекаем клик по алёрту и редиректим на источник.

Ссылка в уведомлении ведёт сюда (а не напрямую на OLX/Uybor), чтобы мерить
CTR. Раньше была в inline-кнопке (Telegram не префетчит кнопки), но кнопка
заставляла Telegram показывать экран-подтверждение перехода — поэтому ссылку
вернули прямо в текст. Чтобы боты-префетчеры (превью Telegram и т.п.) не
накручивали клики, считаем переход только если User-Agent не похож на бота.
Любой сбой/левый токен → редирект на главную, чтобы юзер не упёрся в тупик.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AlertSend, Listing
from app.services.click_token import unsign_send

router = APIRouter(tags=["redirect"])

HOME = "https://uyradar.uz/"

# Подстроки User-Agent, по которым отсекаем не-людей (префетч/превью/краулеры).
_BOT_UA_MARKERS = ("bot", "preview", "crawler", "spider", "facebookexternalhit", "telegram")


def _is_bot(user_agent: str) -> bool:
    ua = user_agent.lower()
    return not ua or any(m in ua for m in _BOT_UA_MARKERS)


@router.get("/r/{token}", include_in_schema=False)
def track_click(token: str, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    send_id = unsign_send(token)
    if send_id is None:
        return RedirectResponse(HOME, status_code=302)

    send = db.get(AlertSend, send_id)
    if send is None:
        return RedirectResponse(HOME, status_code=302)

    # Уникальный клик: фиксируем только первый раз и только от живого человека.
    if send.clicked_at is None and not _is_bot(request.headers.get("user-agent", "")):
        send.clicked_at = datetime.utcnow()
        db.commit()

    listing = db.get(Listing, send.listing_id) if send.listing_id else None
    target = listing.url if listing and listing.url else HOME
    return RedirectResponse(target, status_code=302)
