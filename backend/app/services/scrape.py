from __future__ import annotations

import threading
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Listing, ScrapeRun, ScrapeTask
from app.scrapers.registry import ADAPTERS, get_adapter, parse_fixture
from app.services import scrape_progress
from app.services.listings import upsert_raw_listing
from app.services.normalization import price_per_m2, to_usd


def resolve_sources(source: str) -> list[str]:
    if not source or source == "all":
        return list(ADAPTERS.keys())
    sources = [item.strip() for item in source.split(",") if item.strip()]
    return sources or list(ADAPTERS.keys())


def resolve_live_sources(source: str) -> list[str]:
    sources = resolve_sources(source)
    return [source_name for source_name in sources if get_adapter(source_name).supports_live]


def run_scrape_for_source(db: Session, source: str, mode: str = "auto") -> ScrapeRun:
    settings = get_settings()
    scrape_progress.set_current_source(source)
    run = ScrapeRun(source=source, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        adapter = get_adapter(source)
        use_live = mode == "live" or (mode == "auto" and settings.allow_live_scraping)
        use_live = use_live or mode in {"quick", "full"}
        if use_live:
            new_count, updated_count = _run_live_scan(
                db,
                adapter,
                mode=mode,
                max_pages=settings.live_scrape_max_pages,
                delay_seconds=settings.live_scrape_delay_seconds,
                quick_known_stop_threshold=settings.quick_known_stop_threshold,
                min_price_usd=settings.min_listing_price_usd,
                min_price_per_m2_usd=settings.min_listing_price_per_m2_usd,
            )
        else:
            raw_listings = parse_fixture(source)
            new_count = 0
            updated_count = 0
            for raw in raw_listings:
                if not _is_plausible_listing(raw, settings.min_listing_price_usd, settings.min_listing_price_per_m2_usd):
                    continue
                _, is_new = upsert_raw_listing(db, raw)
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1
        run.status = "success"
        run.new_count = new_count
        run.updated_count = updated_count
    except Exception as exc:  # pragma: no cover - defensive run logging
        run.status = "failed"
        run.error = str(exc)
    finally:
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
    return run


def run_scrape(db: Session, source: str = "all", mode: str = "auto") -> list[ScrapeRun]:
    settings = get_settings()
    use_live = mode == "live" or (mode == "auto" and settings.allow_live_scraping)
    use_live = use_live or mode in {"quick", "full"}
    sources = resolve_live_sources(source) if use_live else resolve_sources(source)
    return [run_scrape_for_source(db, source_name, mode=mode) for source_name in sources]


def start_scrape_in_background(source: str = "all", mode: str = "quick") -> bool:
    settings = get_settings()
    use_live = mode == "live" or (mode == "auto" and settings.allow_live_scraping)
    use_live = use_live or mode in {"quick", "full"}
    sources = resolve_live_sources(source) if use_live else resolve_sources(source)
    if not sources:
        return False
    if not scrape_progress.start(mode=mode, sources=sources):
        return False

    with SessionLocal() as db:
        task = ScrapeTask(
            status="running",
            mode=mode,
            sources=",".join(sources),
            current_source=sources[0] if sources else None,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id

    scrape_progress.set_task_id(task_id)

    def _worker() -> None:
        try:
            with SessionLocal() as db:
                for source_name in sources:
                    if scrape_progress.is_stop_requested():
                        break
                    _sync_task_progress(db, task_id, current_source=source_name)
                    run_scrape_for_source(db, source_name, mode=mode)
                final_status = "stopped" if scrape_progress.is_stop_requested() else "success"
                _sync_task_progress(db, task_id, status=final_status, finished=True)
            scrape_progress.finish()
        except Exception as exc:  # pragma: no cover - background safety net
            with SessionLocal() as db:
                _sync_task_progress(db, task_id, status="failed", error=str(exc), finished=True)
            scrape_progress.finish(error=str(exc))

    threading.Thread(target=_worker, daemon=True).start()
    return True


def _sync_task_progress(
    db: Session,
    task_id: int,
    *,
    current_source: str | None = None,
    status: str | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    task = db.get(ScrapeTask, task_id)
    if not task:
        return
    state = scrape_progress.get_state()
    task.pages_scanned = state["pages_scanned"]
    task.found_count = state["found_total"]
    task.new_count = state["new_total"]
    task.updated_count = state["updated_total"]
    if current_source is not None:
        task.current_source = current_source
    if status is not None:
        task.status = status
    if error is not None:
        task.error = error
    if finished:
        task.finished_at = datetime.utcnow()
        task.current_source = None
    db.commit()


def get_source_page_stats(source: str = "all") -> list[dict]:
    stats = []
    for source_name in resolve_sources(source):
        adapter = get_adapter(source_name)
        item = {
            "source": source_name,
            "supports_live": adapter.supports_live,
            "total_pages": None,
            "page_size": adapter.page_size,
            "total_listings": None,
            "error": None,
        }
        if not adapter.supports_live:
            item["error"] = "Live scraping is not implemented"
            stats.append(item)
            continue
        try:
            page_stats = adapter.count_live_pages()
            item.update(
                {
                    "total_pages": page_stats.total_pages,
                    "page_size": page_stats.page_size,
                    "total_listings": page_stats.total_listings,
                }
            )
        except Exception as exc:  # pragma: no cover - network state is external
            item["error"] = str(exc)
        stats.append(item)
    return stats


def _run_live_scan(
    db: Session,
    adapter,
    *,
    mode: str,
    max_pages: int,
    delay_seconds: float,
    quick_known_stop_threshold: int,
    min_price_usd: float,
    min_price_per_m2_usd: float,
) -> tuple[int, int]:
    page_limit = None if mode in {"quick", "full"} else max_pages
    known_stop = quick_known_stop_threshold if mode == "quick" else None
    known_total = 0
    new_count = 0
    updated_count = 0

    for page_listings in adapter.fetch_live_pages(max_pages=page_limit, delay_seconds=delay_seconds):
        page_new = 0
        page_updated = 0
        page_found = len(page_listings)
        for raw in page_listings:
            if not _is_plausible_listing(raw, min_price_usd, min_price_per_m2_usd):
                continue
            known_before = _is_known_listing(db, raw.source, raw.source_id)
            _, is_new = upsert_raw_listing(db, raw)
            if is_new:
                new_count += 1
                page_new += 1
            else:
                updated_count += 1
                page_updated += 1
                if known_before:
                    known_total += 1
        db.commit()
        scrape_progress.increment(pages=1, found=page_found, new=page_new, updated=page_updated)
        _sync_task_from_progress(db)
        if scrape_progress.is_stop_requested():
            return new_count, updated_count
        if known_stop and known_total >= known_stop:
            return new_count, updated_count

    return new_count, updated_count


def _sync_task_from_progress(db: Session) -> None:
    state = scrape_progress.get_state()
    task_id = state.get("task_id")
    if not task_id:
        return
    task = db.get(ScrapeTask, task_id)
    if not task:
        return
    task.pages_scanned = state["pages_scanned"]
    task.found_count = state["found_total"]
    task.new_count = state["new_total"]
    task.updated_count = state["updated_total"]
    task.current_source = state.get("current_source")
    db.commit()


def _is_known_listing(db: Session, source: str, source_id: str) -> bool:
    return db.scalar(select(Listing.id).where(Listing.source == source, Listing.source_id == source_id)) is not None


def _is_plausible_listing(raw, min_price_usd: float, min_price_per_m2_usd: float) -> bool:
    price_usd = to_usd(raw.price, raw.currency)
    return price_usd >= min_price_usd and price_per_m2(price_usd, raw.area_m2) >= min_price_per_m2_usd
