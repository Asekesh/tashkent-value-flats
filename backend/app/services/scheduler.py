from __future__ import annotations

import asyncio
import contextlib

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.scrape import run_scrape


async def scheduled_scrape_loop() -> None:
    settings = get_settings()
    interval_seconds = max(1, settings.scrape_interval_minutes) * 60
    while True:
        await asyncio.to_thread(_run_once)
        await asyncio.sleep(interval_seconds)


def _run_once() -> None:
    settings = get_settings()
    if not settings.allow_live_scraping:
        return
    with SessionLocal() as db:
        for source in settings.scheduled_source_list:
            run_scrape(db, source=source, mode=settings.scheduled_scrape_mode)


async def stop_scheduler(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
