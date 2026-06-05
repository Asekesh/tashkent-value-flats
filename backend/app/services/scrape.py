from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Listing, ScrapeRun, ScrapeTask
from app.scrapers.base import RawListing
from app.scrapers.registry import ADAPTERS, get_adapter, parse_fixture
from app.services import archive_sweep, scrape_progress
from app.services.listings import mark_delisted_for_source, upsert_raw_listing
from app.services.normalization import price_per_m2, to_usd


_DETAIL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TashkentValueFlats/0.1; +https://github.com/Asekesh/tashkent-value-flats)",
    "Accept-Language": "ru,en;q=0.8",
}

# Ratio window (search-card UZS->USD estimate / stored detail-confirmed USD)
# where a refresh of a known OLX-USD listing is plausibly just fixed-rate FX
# noise around the same у.е. ask. Inside it the upsert preserve guard holds the
# price and we skip the HTTP probe; outside it the search price moved enough to
# signal a real change, so we re-probe the detail page for the true USD ask
# instead of trusting the lossy UZS estimate. Asymmetric like to_usd's bias.
_OLX_FX_NOISE_LO = 0.90
_OLX_FX_NOISE_HI = 1.02


def resolve_sources(source: str) -> list[str]:
    if not source or source == "all":
        return list(ADAPTERS.keys())
    sources = [item.strip() for item in source.split(",") if item.strip()]
    return sources or list(ADAPTERS.keys())


def resolve_live_sources(source: str) -> list[str]:
    sources = resolve_sources(source)
    return [source_name for source_name in sources if get_adapter(source_name).supports_live]


def run_scrape_for_source(db: Session, source: str, mode: str = "auto", trigger: str = "manual") -> ScrapeRun:
    settings = get_settings()
    scrape_progress.set_current_source(source)
    run = ScrapeRun(source=source, status="running", trigger=trigger)
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
                settings=settings,
            )
        else:
            # Fixture-режим — только для sale: rent-фикстур нет, rent-адаптер
            # унаследовал бы sale-фикстуру (olx.html/uybor.html) и, матчась по
            # (source, source_id), перезаписал бы sale-строки как rent. Прод —
            # live-режим; fixture только dev/CI.
            raw_listings = parse_fixture(source) if adapter.deal_type == "sale" else []
            new_count = 0
            updated_count = 0
            for raw in raw_listings:
                if not _is_plausible_listing(raw, settings):
                    continue
                _, is_new = upsert_raw_listing(db, raw)
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1
        run.status = "success"
        run.new_count = new_count
        run.updated_count = updated_count
        if use_live and mode in {"full", "live"}:
            mark_delisted_for_source(db, adapter.source, deal_type=adapter.deal_type)
            # Свип запускаем только из sale-джоба: он и так покрывает ВСЕ source=='olx'
            # строки (включая аренду), поэтому второй запуск из olx_rent — лишний.
            if adapter.source == "olx" and adapter.deal_type == "sale":
                # OLX hides archived ads from search immediately; the 3-day
                # delist heuristic above is too slow, so probe detail pages.
                db.commit()
                archive_sweep.start_sweep_in_background()
    except Exception as exc:  # pragma: no cover - defensive run logging
        run.status = "failed"
        run.error = str(exc)
    finally:
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
    return run


def run_scrape(db: Session, source: str = "all", mode: str = "auto", trigger: str = "manual") -> list[ScrapeRun]:
    settings = get_settings()
    use_live = mode == "live" or (mode == "auto" and settings.allow_live_scraping)
    use_live = use_live or mode in {"quick", "full"}
    sources = resolve_live_sources(source) if use_live else resolve_sources(source)
    return [run_scrape_for_source(db, source_name, mode=mode, trigger=trigger) for source_name in sources]


def start_scrape_in_background(source: str = "all", mode: str = "quick", trigger: str = "manual") -> bool:
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
            trigger=trigger,
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
                    run_scrape_for_source(db, source_name, mode=mode, trigger=trigger)
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
    settings,
) -> tuple[int, int]:
    page_limit = None if mode in {"quick", "full"} else max_pages
    known_stop = quick_known_stop_threshold if mode == "quick" else None
    known_total = 0
    new_count = 0
    updated_count = 0
    detail_client = (
        httpx.Client(timeout=25, follow_redirects=True, headers=_DETAIL_HEADERS)
        if getattr(adapter, "source", None) == "olx"
        else None
    )

    try:
        for page_listings in adapter.fetch_live_pages(max_pages=page_limit, delay_seconds=delay_seconds):
            page_new = 0
            page_updated = 0
            page_found = len(page_listings)
            for raw in page_listings:
                known_before = _is_known_listing(db, raw.source, raw.source_id)
                if detail_client is not None:
                    if not known_before:
                        raw = _probe_new_olx_listing(raw, adapter, detail_client)
                        if raw is None:
                            continue
                    elif mode == "quick":
                        # Re-probe known OLX-USD movers only in quick scans (bounded
                        # by known_stop). Full scans skip it: their post-scan
                        # archive_sweep already re-probes every active OLX detail
                        # page, so re-probing here would just duplicate that work and
                        # — on a market-wide FX move that pushes every row out of the
                        # window — fire an unbounded sequential probe storm.
                        raw = _reprobe_known_olx_listing(db, raw, adapter, detail_client)
                if not _is_plausible_listing(raw, settings):
                    continue
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
    finally:
        if detail_client is not None:
            detail_client.close()

    return new_count, updated_count


def _probe_new_olx_listing(raw: RawListing, adapter, client: httpx.Client) -> RawListing | None:
    """Read OLX detail-only fields before the first save.

    Search pages report every price as UZS. The detail page preserves the
    seller's original у.е. currency, so first-time OLX rows must be probed
    before upsert to avoid showing the ~5% low converted price even briefly.
    Returns the detail-merged raw (currency rewritten to USD when the seller
    listed in у.е.), or ``None`` when the ad is gone / the probe raised — the
    caller then skips the row and retries on the next quick scan.
    """
    try:
        probe = adapter.probe_listing(raw.url, client)
    except Exception:
        return None
    if probe.is_gone:
        return None
    updates: dict = {}
    if probe.usd_price is not None:
        updates["price"] = probe.usd_price
        updates["currency"] = "USD"
    if probe.photos:
        updates["photos"] = probe.photos
    if probe.floor is not None:
        updates["floor"] = probe.floor
    if probe.total_floors is not None:
        updates["total_floors"] = probe.total_floors
    return replace(raw, **updates) if updates else raw


def _reprobe_known_olx_listing(db: Session, raw: RawListing, adapter, client: httpx.Client) -> RawListing:
    """Re-probe a KNOWN OLX listing's detail page when its search-card price
    moved enough to signal a real change.

    A stored detail-confirmed USD ask is preserved against search-page UZS in
    upsert (``listings._should_preserve_olx_detail_price``), so fixed-rate FX
    noise never corrupts it. The flip side is that a genuine seller price change
    would stay frozen until the next archive_sweep. When the incoming search
    estimate leaves the FX-noise window we re-probe the detail page so the real
    change is captured immediately and accurately (true у.е. ask, not the
    ~5%-low UZS estimate); the resulting raw carries currency=USD, so upsert
    takes the normal update path and logs a correct price_changed event.

    On probe failure (gone / network) the raw is returned unchanged: the upsert
    preserve guard then keeps the existing USD — a quick scan never rolls a
    detail-confirmed USD price back to the search-page UZS estimate.
    """
    if raw.currency.upper() != "UZS":
        return raw
    listing = db.scalar(
        select(Listing).where(Listing.source == raw.source, Listing.source_id == raw.source_id)
    )
    if listing is None or (listing.currency or "").upper() != "USD" or not listing.price_usd:
        return raw
    incoming_usd = to_usd(raw.price, raw.currency)
    if not incoming_usd or listing.price_usd <= 0:
        return raw
    ratio = incoming_usd / listing.price_usd
    if _OLX_FX_NOISE_LO <= ratio <= _OLX_FX_NOISE_HI:
        return raw
    probed = _probe_new_olx_listing(raw, adapter, client)
    return probed if probed is not None else raw


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


def _is_plausible_listing(raw, settings) -> bool:
    # Пороги зависят от типа сделки (у аренды цена/м² в ~100x меньше) — единый
    # хелпер settings.price_floors, чтобы маппинг не дублировался.
    min_price_usd, min_price_per_m2_usd = settings.price_floors(raw.deal_type)
    price_usd = to_usd(raw.price, raw.currency)
    return price_usd >= min_price_usd and price_per_m2(price_usd, raw.area_m2) >= min_price_per_m2_usd
