# Анонс аренды — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Разово сообщить активным пользователям бота, что появились уведомления об аренде, и упомянуть аренду в welcome/help для новичков.

**Architecture:** Standalone-скрипт `app.scripts.announce_rent` (запуск `railway run`), рассылка через Telegram Bot API синхронным httpx с throttle/429/403, курсорный резюм `--after-id`. Плюс i18n-ключ анонса и правки welcome/help.

**Tech Stack:** Python 3.9, httpx, SQLAlchemy, aiogram-типы (InlineKeyboardMarkup), Telegram Bot API.

Спека: `docs/superpowers/specs/2026-06-22-announce-rent-design.md`

---

### Task 1: i18n — ключ анонса + правки welcome/help

**Files:** Modify `backend/app/bot/i18n.py`

- [ ] **Step 1: Добавить ключ `announce_rent`** (ru/uz), в стиле существующих многострочных ключей:
  - ru: `"🔑 <b>Теперь есть уведомления об аренде!</b>\n\nБот ищет квартиры не только на продажу, но и в аренду — можно с фильтром «без комиссии».\n\nНажмите «➕ Новое уведомление» и выберите «Снять» на первом шаге."`
  - uz: `"🔑 <b>Endi ijara bo'yicha bildirishnomalar bor!</b>\n\nBot kvartiralarni nafaqat sotuvga, balki ijaraga ham qidiradi — «komissiyasiz» filtri bilan.\n\n«➕ Yangi bildirishnoma» tugmasini bosing va birinchi qadamda «Ijara»ni tanlang."`

- [ ] **Step 2: Правка `welcome`** — упомянуть продажу и аренду:
  - ru: `"Привет! 👋\n\nЯ собираю объявления о квартирах в Ташкенте — <b>на продажу и в аренду</b> — сразу с трёх площадок (OLX, Uybor, Realt24) и присылаю уведомление, как только появится вариант под ваш фильтр.\n\nПросто нажмите кнопку ниже — настроим за минуту 👇"`
  - uz: `"Salom! 👋\n\nMen Toshkentdagi kvartira e'lonlarini — <b>sotuv va ijara</b> — bir vaqtda uch saytdan to'playman (OLX, Uybor, Realt24) va filtringizga mos variant chiqishi bilanoq xabar yuboraman.\n\nQuyidagi tugmani bosing — bir daqiqada sozlaymiz 👇"`

- [ ] **Step 3: Правка `help`** — в вводной строке добавить «на продажу и в аренду», в шаг 1 — «(продажа или аренда, район…)»:
  - ru intro: `"🤖 Бот следит за новыми объявлениями по Ташкенту — на продажу и в аренду — и шлёт вам уведомления, как только появится подходящая квартира."` ; шаг 1: `"1️⃣ Нажмите <b>«➕ Новое уведомление»</b> и за пару шагов задайте фильтр (продажа или аренда, район, комнаты, цена…)."` (остальные строки help без изменений)
  - uz intro: `"🤖 Bot Toshkent bo'yicha yangi e'lonlarni — sotuv va ijara — kuzatadi va mos kvartira paydo bo'lishi bilanoq sizga xabar yuboradi."` ; шаг 1: `"1️⃣ <b>«➕ Yangi bildirishnoma»</b> tugmasini bosing va bir necha qadamda filtr belgilang (sotuv yoki ijara, tuman, xonalar, narx…)."`

- [ ] **Step 4: Verify** — `cd backend && python3 -c "from app.bot.i18n import t; print(t('announce_rent','ru')); print(t('announce_rent','uz')); print('аренду' in t('welcome','ru'), 'ijara' in t('welcome','uz'))"` → текст печатается, оба True.

- [ ] **Step 5: Commit** — `git add backend/app/bot/i18n.py && git commit -m "feat(bot): анонс аренды в i18n + упоминание аренды в welcome/help"`

---

### Task 2: Скрипт рассылки `announce_rent.py`

**Files:**
- Create `backend/app/scripts/__init__.py` (пустой)
- Create `backend/app/scripts/announce_rent.py`

- [ ] **Step 1: Создать пакет** — пустой `backend/app/scripts/__init__.py`.

- [ ] **Step 2: Написать скрипт** `backend/app/scripts/announce_rent.py`:

```python
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
    for attempt in range(2):
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
            return "blocked"
        if resp.status_code == 429:
            retry = resp.json().get("parameters", {}).get("retry_after", 1)
            time.sleep(retry + 1)
            continue  # один повтор
        logger.error("send to %s -> %s %s", chat_id, resp.status_code, resp.text[:200])
        return "failed"
    return "failed"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    token = settings.telegram_bot_token
    if not token and not args.dry_run:
        raise SystemExit("telegram_bot_token не задан")

    with SessionLocal() as db:
        stmt = (
            select(User)
            .where(User.telegram_id.is_not(None), User.is_active.is_(True), User.id > args.after_id)
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
```

ВАЖНО: перед написанием открыть `backend/app/core/config.py` и `backend/app/models/__init__.py`, подтвердить: `get_settings().telegram_bot_token`, `User.telegram_id`, `User.is_active`, `User.lang`, `User.id` существуют (см. handlers.py — все используются там). `normalize_lang`/`t` импортируются из `app.bot.i18n` (используются в notifier.py). Подстроить под фактические имена, если отличаются — не выдумывать.

- [ ] **Step 3: Проверка импорта + dry-run на тестовой БД** — `cd backend && python3 -c "from app.scripts import announce_rent; print('import ok')"`. Полноценный dry-run против пустой/тестовой БД: `cd backend && python3 -m app.scripts.announce_rent --dry-run` → печатает «получателей: 0» (локально БД пустая) без ошибок и без отправок.

- [ ] **Step 4: Commit** — `git add backend/app/scripts/ && git commit -m "feat(bot): скрипт разовой рассылки анонса аренды (railway run)"`

---

### Task 3: Финальная проверка

- [ ] **Step 1:** `cd backend && python3 -m pytest -q` — регрессий нет.
- [ ] **Step 2:** smoke — `cd backend && python3 -c "from app.bot import i18n; from app.scripts import announce_rent; print('ok')"`.

---

## Деплой / запуск

1. «Запушить» → деплой (welcome/help обновятся сразу для всех).
2. После успешного деплоя — РАЗОВО: `railway run -s Postgres python -m app.scripts.announce_rent --dry-run` (проверить число), затем без `--dry-run`.
3. При обрыве — повторить с `--after-id <last_id>` из вывода.
