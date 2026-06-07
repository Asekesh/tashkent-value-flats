from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import ScrapeRun, ScrapeTask
from app.schemas.listing import ScrapeRunOut, ScrapeRunRequest, ScrapeSourceOut, ScrapeTaskOut
from app.services import archive_sweep, market_recompute, photo_backfill, scrape_progress
from app.services.dedup import merge_existing_duplicates
from app.services.listings import backfill_residential_complexes, remerge_residential_complexes
from app.services.scrape import get_source_page_stats, start_scrape_in_background

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/scrape/run")
def run_scrape(payload: ScrapeRunRequest) -> dict:
    started = start_scrape_in_background(source=payload.source, mode=payload.mode, trigger="manual")
    if not started:
        state = scrape_progress.get_state()
        if state["is_running"]:
            return {"started": False, "reason": "already_running", "progress": state}
        raise HTTPException(status_code=400, detail="No live sources available")
    return {"started": True, "progress": scrape_progress.get_state()}


@router.get("/scrape/progress")
def get_progress() -> dict:
    return scrape_progress.get_state()


@router.post("/scrape/stop")
def stop_scrape() -> dict:
    accepted = scrape_progress.request_stop()
    return {"stopped": accepted, "progress": scrape_progress.get_state()}


@router.get("/scrape/runs", response_model=list[ScrapeRunOut])
def get_scrape_runs(db: Session = Depends(get_db)) -> list[ScrapeRunOut]:
    return list(db.scalars(select(ScrapeRun).order_by(desc(ScrapeRun.started_at)).limit(50)).all())


@router.get("/scrape/tasks", response_model=list[ScrapeTaskOut])
def get_scrape_tasks(db: Session = Depends(get_db)) -> list[ScrapeTaskOut]:
    return list(db.scalars(select(ScrapeTask).order_by(desc(ScrapeTask.started_at)).limit(30)).all())


@router.get("/scrape/sources", response_model=list[ScrapeSourceOut])
def get_scrape_sources(source: str = "all") -> list[ScrapeSourceOut]:
    return [ScrapeSourceOut(**item) for item in get_source_page_stats(source)]


@router.post("/backfill/olx-photos")
def run_olx_photo_backfill() -> dict:
    started = photo_backfill.start_photo_backfill_in_background()
    if not started:
        return {"started": False, "reason": "already_running", "progress": photo_backfill.get_state()}
    return {"started": True, "progress": photo_backfill.get_state()}


@router.get("/backfill/progress")
def get_backfill_progress() -> dict:
    return photo_backfill.get_state()


@router.post("/backfill/stop")
def stop_olx_photo_backfill() -> dict:
    stopped = photo_backfill.request_stop()
    return {"stopped": stopped, "progress": photo_backfill.get_state()}


@router.post("/sweep/olx-archived")
def run_olx_archive_sweep() -> dict:
    started = archive_sweep.start_sweep_in_background()
    if not started:
        return {"started": False, "reason": "already_running", "progress": archive_sweep.get_state()}
    return {"started": True, "progress": archive_sweep.get_state()}


@router.get("/sweep/progress")
def get_sweep_progress() -> dict:
    return archive_sweep.get_state()


@router.post("/sweep/stop")
def stop_olx_archive_sweep() -> dict:
    stopped = archive_sweep.request_stop()
    return {"stopped": stopped, "progress": archive_sweep.get_state()}


@router.post("/dedup/merge")
def merge_duplicate_listings(dry_run: bool = False, db: Session = Depends(get_db)) -> dict:
    return merge_existing_duplicates(db, dry_run=dry_run)


@router.post("/complex/backfill")
def backfill_complexes(
    dry_run: bool = False, limit: Optional[int] = None, after_id: int = 0, db: Session = Depends(get_db)
) -> dict:
    return backfill_residential_complexes(db, dry_run=dry_run, limit=limit, after_id=after_id)


@router.post("/complex/remerge")
def remerge_complexes(dry_run: bool = False, db: Session = Depends(get_db)) -> dict:
    """Схлопывает дубли ЖК под обновлённый нормализатор. Запускать один раз
    после деплоя. dry_run=true — только посчитать, без изменений."""
    return remerge_residential_complexes(db, dry_run=dry_run)


@router.post("/market/recompute")
def recompute_market() -> dict:
    """Полный серверный пересчёт кэш-оценок рынка (market_price/discount/
    is_below_market) для всех активных листингов, в фоне. Дёргать вручную
    после изменения логики CMA — чтобы не ждать недельного rebuild."""
    started = market_recompute.start_market_recompute_in_background()
    if not started:
        return {"started": False, "reason": "already_running", "progress": market_recompute.get_state()}
    return {"started": True, "progress": market_recompute.get_state()}


@router.get("/market/recompute/progress")
def get_market_recompute_progress() -> dict:
    return market_recompute.get_state()


@router.post("/sweep/listing/{listing_id}")
def sweep_single_listing(listing_id: int) -> dict:
    return archive_sweep.probe_one_listing(listing_id)
