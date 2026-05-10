from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func

from app.api import admin, listings
from app.core.config import get_settings
from app.db.session import Base, SessionLocal, engine
from app.models import Listing  # noqa: F401
from app.scrapers.registry import ADAPTERS, parse_fixture
from app.services.listings import upsert_raw_listing
from app.services.scheduler import scheduled_scrape_loop, stop_scheduler


settings = get_settings()
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    scheduler_task: asyncio.Task | None = None
    if settings.seed_fixtures_on_startup:
        with SessionLocal() as db:
            count = db.scalar(select(func.count()).select_from(Listing))
            if not count:
                for source in ADAPTERS:
                    for raw in parse_fixture(source):
                        upsert_raw_listing(db, raw)
                db.commit()
    if settings.enable_scrape_scheduler and settings.allow_live_scraping:
        scheduler_task = asyncio.create_task(scheduled_scrape_loop())
    yield
    await stop_scheduler(scheduler_task)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(listings.router)
app.include_router(admin.router)
