from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import User

logger = logging.getLogger(__name__)

_KIND_LABEL = {"bug": "🐞 Ошибка", "feature": "💡 Пожелание"}
_SOURCE_LABEL = {"web": "сайт", "bot": "бот"}


def notify_admins_new_feedback(
    kind: str, message: str, contact: str | None, source: str
) -> None:
    """Прислать всем админам в Telegram пинг о новом тикете обратной связи.

    Синхронный httpx прямо в Bot API — как в notifier._send_listing_sync
    (через aiogram.Bot из чужого event loop ходить нельзя). Любые ошибки
    глушим: пинг не должен ронять создание тикета.
    """
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        return

    try:
        with SessionLocal() as db:
            admin_ids = [
                u.telegram_id
                for u in db.scalars(
                    select(User).where(
                        User.role == "admin", User.is_active.is_(True)
                    )
                ).all()
                if u.telegram_id
            ]
        if not admin_ids:
            return

        import html

        kind_label = _KIND_LABEL.get(kind, kind)
        source_label = _SOURCE_LABEL.get(source, source)
        from_line = f"\n👤 {html.escape(contact)}" if contact else ""
        text = (
            f"📨 <b>Новая обратная связь</b> · {kind_label}\n"
            f"Источник: {source_label}{from_line}\n\n"
            f"{html.escape(message[:3500])}"
        )

        import httpx

        with httpx.Client(timeout=10.0) as client:
            for chat_id in admin_ids:
                try:
                    client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                        },
                    )
                except Exception:
                    logger.exception("feedback ping to %s failed", chat_id)
    except Exception:
        logger.exception("notify_admins_new_feedback failed")
