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


def send_feedback_reply(
    telegram_id: int, reply_text: str, original_message: str | None = None
) -> bool:
    """Отправить ответ админа пользователю в Telegram. Возвращает True при успехе.

    Тот же синхронный httpx прямо в Bot API. Ошибки логируем и возвращаем False,
    чтобы вызывающий не записывал ответ как доставленный.
    """
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        logger.warning("send_feedback_reply: no bot token")
        return False

    import html

    quote = ""
    if original_message:
        snippet = html.escape(original_message[:200])
        quote = f"\n\n<i>На ваше сообщение:</i>\n<blockquote>{snippet}</blockquote>"
    text = (
        "💬 <b>Ответ от поддержки uyradar.uz</b>\n\n"
        f"{html.escape(reply_text[:3500])}{quote}"
    )

    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": telegram_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        return resp.status_code == 200
    except Exception:
        logger.exception("send_feedback_reply to %s failed", telegram_id)
        return False
