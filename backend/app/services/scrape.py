from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ScrapeRun
from app.scrapers.registry import ADAPTERS, get_adapter, parse_fixture
from app.services.listings import upsert_raw_listing


def resolve_sources(source: str) -> list[str]:
    return list(ADAPTERS.keys()) if source == "all" else [source]


def run_scrape_for_source(db: Session, source: str, mode: str = "auto") -> ScrapeRun:
    settings = get_settings()
    run = ScrapeRun(source=source, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        adapter = get_adapter(source)
        use_live = mode == "live" or (mode == "auto" and settings.allow_live_scraping)
        if use_live:
            raw_listings = adapter.fetch_live(
                max_pages=settings.live_scrape_max_pages,
                delay_seconds=settings.live_scrape_delay_seconds,
            )
        else:
            raw_listings = parse_fixture(source)
        new_count = 0
        updated_count = 0
        for raw in raw_listings:
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
    return [run_scrape_for_source(db, source_name, mode=mode) for source_name in resolve_sources(source)]

