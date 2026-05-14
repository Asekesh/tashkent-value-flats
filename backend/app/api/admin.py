from __future__ import annotations

import re

import httpx
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


@router.get("/debug/olx-photos")
def debug_olx_photos(page: int = 1) -> dict:
    """Temporary diagnostic: shows what OLX returns to the prod server and how
    many photos the adapter manages to extract from it."""
    from app.scrapers.adapters.olx import OlxAdapter, _extract_prerendered_photos

    adapter = OlxAdapter()
    url = adapter.search_url if page == 1 else f"{adapter.search_url}?page={page}"
    with httpx.Client(
        timeout=25,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; TashkentValueFlats/0.1; +https://github.com/Asekesh/tashkent-value-flats)",
            "Accept-Language": "ru,en;q=0.8",
        },
    ) as client:
        response = client.get(url)
        html = response.text

    state_match = re.search(
        r"window\.__PRERENDERED_STATE__\s*=\s*(\"(?:[^\"\\]|\\.)*\")", html
    )
    photo_map = _extract_prerendered_photos(html)
    listings = adapter.parse_live_page(html)
    with_photos = [item for item in listings if item.photos]
    return {
        "url": url,
        "status": response.status_code,
        "html_len": len(html),
        "has_state_marker": "__PRERENDERED_STATE__" in html,
        "state_regex_matched": bool(state_match),
        "photo_map_size": len(photo_map),
        "cards": html.count('data-cy="l-card"'),
        "listings_parsed": len(listings),
        "listings_with_photos": len(with_photos),
        "sample": [
            {"source_id": item.source_id, "photos": item.photos[:1]}
            for item in listings[:5]
        ],
        "html_head": html[:600],
    }


@router.get("/debug/olx-scan")
def debug_olx_scan(max_pages: int = 3) -> dict:
    """Temporary diagnostic: runs the real fetch_live_pages() loop (single
    client, sequential pages) exactly like the scraper does, and reports
    per-page photo coverage — to tell apart a fetch problem from a parse one."""
    from app.scrapers.adapters.olx import OlxAdapter

    adapter = OlxAdapter()
    pages = []
    for index, page_listings in enumerate(
        adapter.fetch_live_pages(max_pages=max_pages, delay_seconds=2.0), start=1
    ):
        with_photos = sum(1 for item in page_listings if item.photos)
        pages.append(
            {
                "page": index,
                "listings": len(page_listings),
                "with_photos": with_photos,
                "sample": [
                    {"source_id": item.source_id, "photos": item.photos[:1]}
                    for item in page_listings[:3]
                ],
            }
        )
    total = sum(p["listings"] for p in pages)
    total_with = sum(p["with_photos"] for p in pages)
    return {"total": total, "total_with_photos": total_with, "pages": pages}
