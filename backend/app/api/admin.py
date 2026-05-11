from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import ScrapeRun, ScrapeTask
from app.schemas.listing import ScrapeRunOut, ScrapeRunRequest, ScrapeSourceOut, ScrapeTaskOut
from app.services import scrape_progress
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
