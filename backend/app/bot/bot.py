from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonCommands

from app.bot.handlers import router
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_bot: Optional[Bot] = None


def build_bot() -> Optional[Bot]:
    """Создать (или вернуть закешированный) экземпляр Bot.

    Возвращает None если токен не задан — этим notifier тоже отключается.
    """
    global _bot
    if _bot is not None:
        return _bot
    settings = get_settings()
    if not settings.telegram_bot_token:
        return None
    _bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    return _bot


async def _setup_commands(bot: Bot) -> None:
    """Меню команд (синяя кнопка слева от поля ввода)."""
    await bot.set_my_commands([
        BotCommand(command="new", description="➕ Уведомления о новых квартирах"),
        BotCommand(command="list", description="📋 Мои уведомления"),
        BotCommand(command="help", description="ℹ️ Помощь"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def start_bot_polling() -> None:
    """Long-running task: long-poll Telegram and dispatch updates."""
    bot = build_bot()
    if bot is None:
        logger.info("telegram_bot_token не задан — бот выключен")
        return
    with contextlib.suppress(Exception):
        await _setup_commands(bot)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    try:
        await dp.start_polling(bot, handle_signals=False)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("bot polling crashed")


async def stop_bot(task: asyncio.Task | None) -> None:
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    global _bot
    if _bot is not None:
        with contextlib.suppress(Exception):
            await _bot.session.close()
        _bot = None
