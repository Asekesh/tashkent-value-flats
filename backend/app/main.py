from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, inspect, select, func, text

from app.admin.router import router as admin_panel_router
from app.api import admin, listings, onboarding
from app.auth.router import router as auth_router
from app.bot import notifier_loop, start_bot_polling, stop_bot
from app.core.config import get_settings
from app.legal.router import router as legal_router
from app.db.session import Base, SessionLocal, engine
from app.models import Listing  # noqa: F401
from app.scrapers.registry import ADAPTERS, parse_fixture
from app.services.listings import upsert_raw_listing
from app.services.normalization import normalize_district
from app.services.scheduler import (
    scheduled_market_rebuild_loop,
    scheduled_olx_startup_sweep,
    scheduled_scrape_loop,
    stop_scheduler,
)


settings = get_settings()
STATIC_DIR = Path(__file__).parent / "static"


def _configure_bot_logging() -> None:
    """Поднять INFO-логи бота/notifier/aiogram в stdout Railway.

    uvicorn вешает хендлер только на свои логгеры, рутовый остаётся пустым —
    поэтому INFO от app.bot и aiogram тонут (видны лишь ERROR через lastResort).
    Даём этим двум логгерам собственный stream-хендлер с propagate=False:
    видно `notifier_loop started` и `Run polling for bot ...`, без потопа от
    остального app. Идемпотентно — перезаписываем handlers списком.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    for name in ("app.bot", "aiogram"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        lg.handlers = [handler]
        lg.propagate = False


def _ensure_trigger_columns() -> None:
    inspector = inspect(engine)
    for table in ("scrape_runs", "scrape_tasks"):
        if not inspector.has_table(table):
            continue
        columns = {col["name"] for col in inspector.get_columns(table)}
        if "trigger" in columns:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN trigger VARCHAR(10) DEFAULT 'manual'"))


def _ensure_market_columns() -> None:
    """Бэкап на случай если миграция 0003 не прогналась (dev / старые env).
    В проде это делает Alembic — здесь только safety net."""
    inspector = inspect(engine)
    if not inspector.has_table("listings"):
        return
    existing = {col["name"] for col in inspector.get_columns("listings")}
    additions = (
        ("market_price_per_m2_usd", "FLOAT"),
        ("market_basis", "VARCHAR(40)"),
        ("market_sample_size", "INTEGER DEFAULT 0 NOT NULL"),
        ("market_confidence", "VARCHAR(10)"),
        ("discount_percent", "FLOAT"),
        ("is_below_market", "BOOLEAN DEFAULT 0 NOT NULL"),
        ("savings_usd", "FLOAT"),
        ("market_calculated_at", "DATETIME"),
    )
    with engine.begin() as conn:
        for name, ddl in additions:
            if name in existing:
                continue
            conn.execute(text(f"ALTER TABLE listings ADD COLUMN {name} {ddl}"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    _configure_bot_logging()
    Base.metadata.create_all(bind=engine)
    _ensure_trigger_columns()
    _ensure_market_columns()
    # Base.metadata.create_all уже создаст alerts на пустых БД; в проде
    # Alembic тоже накатит. Доп. safety net не нужен.
    scheduler_task: asyncio.Task | None = None
    olx_sweep_task: asyncio.Task | None = None
    if settings.purge_fixture_listings_on_startup:
        with SessionLocal() as db:
            db.execute(
                delete(Listing).where(
                    Listing.source_id.in_(["olx-1", "olx-2", "olx-3", "uybor-1", "uybor-2", "uybor-3", "realt24-1", "realt24-2", "realt24-3"])
                )
            )
            db.commit()
    with SessionLocal() as db:
        unique_districts = db.scalars(select(Listing.district).distinct()).all()
        changed = 0
        for raw in unique_districts:
            normalized = normalize_district(raw)
            if normalized != raw:
                db.execute(
                    Listing.__table__.update().where(Listing.district == raw).values(district=normalized)
                )
                changed += 1
        if changed:
            db.commit()
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
        # Разовый OLX-sweep: выправляет у.е.-цены, накопленные до этого фикса.
        # Новые OLX-строки пробиваются по detail page прямо во время скана.
        olx_sweep_task = asyncio.create_task(scheduled_olx_startup_sweep())
    # Запускаем market-rebuild loop всегда — он независим от скрейпа.
    # Первый прогон срабатывает сразу если есть листинги без оценки (это
    # покрывает первый деплой: все 11700 листингов получают market_basis
    # за ~2 минуты в фоне, app при этом отвечает).
    market_rebuild_task: asyncio.Task | None = asyncio.create_task(
        scheduled_market_rebuild_loop()
    )
    bot_task: asyncio.Task | None = None
    notifier_task: asyncio.Task | None = None
    if settings.telegram_bot_token:
        bot_task = asyncio.create_task(start_bot_polling())
        notifier_task = asyncio.create_task(notifier_loop())
    yield
    await stop_scheduler(scheduler_task)
    await stop_scheduler(olx_sweep_task)
    await stop_scheduler(market_rebuild_task)
    await stop_scheduler(notifier_task)
    await stop_bot(bot_task)


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
app.include_router(onboarding.router)
app.include_router(auth_router)
app.include_router(admin_panel_router)
app.include_router(legal_router)
