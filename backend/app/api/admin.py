from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import ScrapeRun
from app.schemas.listing import ScrapeRunOut, ScrapeRunRequest
from app.scrapers.registry import ADAPTERS, parse_fixture
from app.services.listings import upsert_raw_listing

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/scrape/run", response_model=list[ScrapeRunOut])
def run_scrape(payload: ScrapeRunRequest, db: Session = Depends(get_db)) -> list[ScrapeRunOut]:
    sources = list(ADAPTERS.keys()) if payload.source == "all" else [payload.source]
    runs: list[ScrapeRun] = []
    for source in sources:
        run = ScrapeRun(source=source, status="running")
        db.add(run)
        db.commit()
        db.refresh(run)
        try:
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
            runs.append(run)
    return runs


@router.get("/scrape/runs", response_model=list[ScrapeRunOut])
def get_scrape_runs(db: Session = Depends(get_db)) -> list[ScrapeRunOut]:
    return list(db.scalars(select(ScrapeRun).order_by(desc(ScrapeRun.started_at)).limit(50)).all())
