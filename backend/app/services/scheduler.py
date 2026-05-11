from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import ScrapeTask
from app.services import scrape_progress
from app.services.scrape import resolve_live_sources, run_scrape_for_source


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
    mode = settings.scheduled_scrape_mode
    sources = resolve_live_sources(",".join(settings.scheduled_source_list))
    if not sources:
        return
    if not scrape_progress.start(mode=mode, sources=sources):
        return

    with SessionLocal() as db:
        task = ScrapeTask(
            status="running",
            trigger="auto",
            mode=mode,
            sources=",".join(sources),
            current_source=sources[0],
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
        scrape_progress.set_task_id(task_id)

        final_status = "success"
        error: str | None = None
        try:
            for source_name in sources:
                if scrape_progress.is_stop_requested():
                    final_status = "stopped"
                    break
                task.current_source = source_name
                db.commit()
                run_scrape_for_source(db, source_name, mode=mode, trigger="auto")
            else:
                if scrape_progress.is_stop_requested():
                    final_status = "stopped"
        except Exception as exc:  # pragma: no cover - defensive
            final_status = "failed"
            error = str(exc)
        finally:
            task.status = final_status
            task.error = error
            task.finished_at = datetime.utcnow()
            task.current_source = None
            state = scrape_progress.get_state()
            task.pages_scanned = state.get("pages_scanned", 0)
            task.found_count = state.get("found_total", 0)
            task.new_count = state.get("new_total", 0)
            task.updated_count = state.get("updated_total", 0)
            db.commit()
            scrape_progress.finish(error=error)


async def stop_scheduler(task: asyncio.Task | None) -> None:
    if not task:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
