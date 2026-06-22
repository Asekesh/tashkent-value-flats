"""Разовая рассылка анонса об аренде активным пользователям бота.

Запуск (один раз, после деплоя Шага 5):
    railway run -s Postgres python -m app.scripts.announce_rent
    railway run -s Postgres python -m app.scripts.announce_rent --dry-run
    railway run -s Postgres python -m app.scripts.announce_rent --after-id 1234

Курсорный резюм (--after-id) на случай обрыва: скрипт печатает последний
обработанный id, продолжать с него — чтобы не разослать дважды.
"""
from __future__ import annotations

import argparse
import logging
import time

import httpx
from sqlalchemy import select

from app.bot.i18n import normalize_lang, t
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import User

logger = logging.getLogger(__name__)

THROTTLE_SECONDS = 0.05  # ~20 сообщений/сек, под лимит Telegram ~30/сек


def _reply_markup(lang: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": t("b_new", lang), "callback_data": "start:new"},
        ]]
    }


def _send(client: httpx.Client, token: str, chat_id: int, lang: str) -> str:
    """Возвращает 'sent' | 'blocked' | 'failed'."""
    payload = {
        "chat_id": chat_id,
        "text": t("announce_rent", lang),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": _reply_markup(lang),
    }
    for _ in range(2):
        try:
            resp = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage", json=payload
            )
        except Exception:
            logger.exception("send to %s failed", chat_id)
            return "failed"
        if resp.status_code == 200:
            return "sent"
        if resp.status_code == 403:
            return "blocked"  # бот заблокирован пользователем
        if resp.status_code == 429:
            retry = resp.json().get("parameters", {}).get("retry_after", 1)
            time.sleep(retry + 1)
            continue  # один повтор после флуд-вейта
        logger.error("send to %s -> %s %s", chat_id, resp.status_code, resp.text[:200])
        return "failed"
    return "failed"


def main() -> None:
    parser = argparse.ArgumentParser(description="Разовый анонс аренды")
    parser.add_argument("--dry-run", action="store_true", help="только посчитать получателей")
    parser.add_argument("--after-id", type=int, default=0, help="слать только пользователям с id > N (резюм)")
    parser.add_argument("--limit", type=int, default=None, help="ограничить число получателей")
    args = parser.parse_args()

    settings = get_settings()
    token = settings.telegram_bot_token
    if not token and not args.dry_run:
        raise SystemExit("telegram_bot_token не задан")

    with SessionLocal() as db:
        # telegram_id у User NOT NULL (бот/веб-логин всегда дают его) — фильтруем
        # только по активности и курсору.
        stmt = (
            select(User)
            .where(User.is_active.is_(True), User.id > args.after_id)
            .order_by(User.id.asc())
        )
        if args.limit:
            stmt = stmt.limit(args.limit)
        users = db.scalars(stmt).all()

    total = len(users)
    print(f"получателей: {total}" + (" (dry-run)" if args.dry_run else ""))
    if args.dry_run or total == 0:
        return

    sent = blocked = failed = 0
    last_id = args.after_id
    with httpx.Client(timeout=10.0) as client:
        for i, u in enumerate(users, 1):
            lang = normalize_lang(u.lang)
            result = _send(client, token, u.telegram_id, lang)
            last_id = u.id
            if result == "sent":
                sent += 1
            elif result == "blocked":
                blocked += 1
                with SessionLocal() as db:
                    db_user = db.get(User, u.id)
                    if db_user is not None:
                        db_user.is_active = False
                        db.commit()
            else:
                failed += 1
            if i % 50 == 0:
                print(f"  {i}/{total} · sent={sent} blocked={blocked} failed={failed} · last_id={last_id}")
            time.sleep(THROTTLE_SECONDS)

    print(f"ГОТОВО: sent={sent} blocked={blocked} failed={failed} · last_id={last_id}")
    print(f"при обрыве продолжить: --after-id {last_id}")


if __name__ == "__main__":
    main()
