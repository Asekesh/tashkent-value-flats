from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import ScrapeRun
from app.schemas.listing import ScrapeRunOut, ScrapeRunRequest
from app.services.scrape import run_scrape as run_scrape_job

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/scrape/run", response_model=list[ScrapeRunOut])
def run_scrape(payload: ScrapeRunRequest, db: Session = Depends(get_db)) -> list[ScrapeRunOut]:
    return run_scrape_job(db, source=payload.source, mode=payload.mode)


@router.get("/scrape/runs", response_model=list[ScrapeRunOut])
def get_scrape_runs(db: Session = Depends(get_db)) -> list[ScrapeRunOut]:
    return list(db.scalars(select(ScrapeRun).order_by(desc(ScrapeRun.started_at)).limit(50)).all())
