from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Listing, ScrapeTask
from app.services import archive_sweep, scrape_progress
from app.services.market_estimate import recompute_all as recompute_market_estimates
from app.services.scrape import resolve_live_sources, run_scrape_for_source
from sqlalchemy import func, select


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


async def scheduled_market_rebuild_loop() -> None:
    """Периодический полный пересчёт оценок рынка для всех листингов.

    Срабатывает один раз при старте, если есть листинги без оценки (первый
    деплой после миграции 0003 — все 11700 без market_basis), и далее раз в
    settings.market_rebuild_interval_hours часов.

    Зачем вообще: каждый upsert считает оценку сразу для изменённого
    листинга, но соседи этого листинга не пересчитываются. Через неделю
    накапливается drift — этот loop его рассасывает.
    """
    settings = get_settings()
    interval_seconds = max(3600, settings.market_rebuild_interval_hours * 3600)

    # Стартовая проверка: если есть листинги без оценки — пересчитываем
    # сразу (этот случай покрывает первый деплой после добавления столбцов).
    await asyncio.to_thread(_rebuild_if_any_pending)

    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(_rebuild_market_estimates)


def _rebuild_if_any_pending() -> None:
    with SessionLocal() as db:
        pending = db.scalar(
            select(func.count())
            .select_from(Listing)
            .where(Listing.status == "active", Listing.market_basis.is_(None))
        )
        if pending and pending > 0:
            recompute_market_estimates(db)


def _rebuild_market_estimates() -> None:
    with SessionLocal() as db:
        try:
            recompute_market_estimates(db)
        except Exception:  # pragma: no cover — не валим scheduler из-за rebuild
            pass


async def scheduled_olx_startup_sweep() -> None:
    """Разовый detail-page sweep активных OLX-объявлений после старта.

    Поисковые страницы OLX всегда отдают цену в UZS, поэтому у.е.-объявление
    лежит на ~5% ниже реальной цены, пока его детальную страницу не опросят.
    Новые OLX-строки пробиваются синхронно в live-scan до сохранения; этот
    разовый проход нужен только для старых накопленных цен после деплоя.
    """
    settings = get_settings()
    if not settings.allow_live_scraping:
        return
    await asyncio.sleep(max(0, settings.olx_sweep_startup_delay_seconds))
    if _has_active_olx():
        # start_* вернёт False, если sweep уже идёт после ручного/full-скана.
        archive_sweep.start_sweep_in_background()


def _has_active_olx() -> bool:
    with SessionLocal() as db:
        return db.scalar(
            select(Listing.id)
            .where(Listing.source == "olx", Listing.status == "active")
            .limit(1)
        ) is not None
