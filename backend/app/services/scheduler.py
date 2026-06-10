from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Listing, ScrapeTask
from app.services import archive_sweep, scrape_progress
from app.services.listings import remerge_residential_complexes
from app.services.market_estimate import recompute_all as recompute_market_estimates
from app.services.scrape import expand_with_rent, resolve_live_sources, run_scrape_for_source
from app.services.seller_classifier import classify_sellers_by_volume
from sqlalchemy import func, select

logger = logging.getLogger("app.scheduler")


async def scheduled_scrape_loop() -> None:
    settings = get_settings()
    interval_seconds = max(1, settings.scrape_interval_minutes) * 60
    while True:
        # Транзиентный сбой (полный диск, обрыв БД) НЕ должен убивать цикл:
        # без этого try одно упавшее _run_once гасит весь скрейп до рестарта.
        try:
            await asyncio.to_thread(_run_once)
        except Exception:  # noqa: BLE001 — логируем и продолжаем по таймеру
            logger.exception("scheduled scrape cycle failed; продолжаю по таймеру")
        await asyncio.sleep(interval_seconds)


def _due_scan_mode(settings) -> str:
    """Какой режим запускать в этом плановом цикле: quick или full.

    quick-скан обрывается после quick_known_stop_threshold известных и не
    дочитывает глубокие страницы, поэтому раз в full_scan_interval_hours
    цикл идёт full — он проходит все страницы и помечает снятые. «Когда был
    последний успешный full» берём из БД (ScrapeTask), чтобы решение
    переживало рестарты/деплои и full не запускался на каждый старт. Ручной
    full из UI тоже сбрасывает таймер (та же таблица).
    """
    base = settings.scheduled_scrape_mode
    interval_hours = settings.full_scan_interval_hours
    if interval_hours <= 0 or base == "full":
        return base
    with SessionLocal() as db:
        last_full = db.scalar(
            select(func.max(ScrapeTask.finished_at)).where(
                ScrapeTask.mode == "full",
                ScrapeTask.status == "success",
            )
        )
    if last_full is None or datetime.utcnow() - last_full >= timedelta(hours=interval_hours):
        return "full"
    return base


def _run_once() -> None:
    settings = get_settings()
    if not settings.allow_live_scraping:
        return
    # Каждая запланированная площадка тянет за собой свой rent-джоб (аренда не
    # перечислена в scheduled_scrape_sources, но должна скрейпиться вместе с sale).
    sources = expand_with_rent(resolve_live_sources(",".join(settings.scheduled_source_list)))
    if not sources:
        return
    mode = _due_scan_mode(settings)
    if not scrape_progress.start(mode=mode, sources=sources):
        return

    # С этого момента scrape_progress в состоянии «running» — finish() обязателен
    # в ЛЮБОМ исходе, иначе следующий цикл навсегда упрётся в start()==False
    # (так и случилось при полном диске: commit ниже падал ДО старого try).
    error: str | None = None
    try:
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
                classify_sellers_by_volume(db)  # agent/owner по объёму после цикла
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
    except Exception as exc:  # сбой ещё до/во время bookkeeping (полный диск и т.п.)
        error = error or str(exc)
        logger.exception("scrape cycle aborted before task bookkeeping")
    finally:
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


async def scheduled_complex_remerge_loop() -> None:
    """Периодическая уборка справочника ЖК: схлопывает дубли-стражглеры, что
    медленно копятся от непойманных шум-слов в новых объявлениях (новые скрейпы
    ключуются правильно, но «Nest One стильная» и т.п. плодят 1-листинговые строки).

    Стартовый прогон (через complex_remerge_startup_delay_seconds после старта) +
    далее раз в complex_remerge_interval_hours. Стартовый нужен, потому что голый
    sleep-таймер сбрасывается на каждом деплое — без него на частых деплоях
    недельный таймер почти никогда бы не срабатывал. На чистом справочнике прогон
    дёшев и не пишет (см. remerge_residential_complexes — идемпотентна)."""
    settings = get_settings()
    interval_seconds = max(3600, settings.complex_remerge_interval_hours * 3600)
    await asyncio.sleep(max(0, settings.complex_remerge_startup_delay_seconds))
    await asyncio.to_thread(_run_complex_remerge)
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(_run_complex_remerge)


def _run_complex_remerge() -> None:
    with SessionLocal() as db:
        try:
            remerge_residential_complexes(db)
        except Exception:  # pragma: no cover — не валим scheduler из-за уборки
            pass


async def scheduled_olx_startup_sweep() -> None:
    """Detail-page sweep активных OLX: разовый после старта + периодический.

    Поисковые страницы OLX отдают цену в UZS и не показывают архивные/снятые
    объявления. detail-проход нужен, чтобы (а) выправлять накопленные у.е.-цены
    и этажи, (б) помечать архивные как removed. Новые строки пробиваются
    синхронно в live-scan, дрейф цен ловит quick-ре-проб, но архивы/снятия
    между сканами вычищает только этот проход — поэтому после стартового он
    повторяется каждые ``olx_sweep_interval_hours`` (0 — без повтора).

    (Имя историческое — изначально проход был только стартовый.)
    """
    settings = get_settings()
    if not settings.allow_live_scraping:
        return
    await asyncio.sleep(max(0, settings.olx_sweep_startup_delay_seconds))
    _maybe_start_olx_sweep()
    interval_hours = settings.olx_sweep_interval_hours
    if interval_hours <= 0:
        return
    # Минимум 1 ч (как у соседних циклов). Sweep сам идемпотентен, так что
    # даже если интервал < длительности прохода — лишний старт просто no-op.
    interval_seconds = max(3600, interval_hours * 3600)
    while True:
        await asyncio.sleep(interval_seconds)
        _maybe_start_olx_sweep()


def _maybe_start_olx_sweep() -> bool:
    """Запустить detail-sweep, если есть активные OLX. Идемпотентно:
    ``start_sweep_in_background`` вернёт False, если sweep уже идёт (после
    ручного/full-скана или ещё не доехавшей прошлой итерации)."""
    if not _has_active_olx():
        return False
    return archive_sweep.start_sweep_in_background()


def _has_active_olx() -> bool:
    with SessionLocal() as db:
        return db.scalar(
            select(Listing.id)
            .where(Listing.source == "olx", Listing.status == "active")
            .limit(1)
        ) is not None
