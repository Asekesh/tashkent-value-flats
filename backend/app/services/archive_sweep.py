"""Detect archived/removed OLX listings and delist them.

OLX hides archived ads from search results within minutes, but the system's
delist heuristic ([mark_delisted_for_source]) waits 3 days of no-shows before
flipping ``status=removed``. In the meantime the dashboard keeps surfacing
ads whose detail pages already say "Объявление в архиве". This sweep walks
every active OLX listing, probes the detail page, and flips archived/gone
ones to ``removed`` immediately.

Triggered automatically after a ``full`` OLX scan and via
POST /api/admin/sweep/olx-archived; progress at GET /api/admin/sweep/progress.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.db.session import SessionLocal
from app.models import Listing, ListingEvent
from app.scrapers.adapters.olx import OlxAdapter
from app.services.normalization import dumps_json, utcnow

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TashkentValueFlats/0.1; +https://github.com/Asekesh/tashkent-value-flats)",
    "Accept-Language": "ru,en;q=0.8",
}
_COMMIT_EVERY = 25


@dataclass
class SweepState:
    is_running: bool = False
    stop_requested: bool = False
    total: int = 0
    processed: int = 0
    archived: int = 0
    photos_filled: int = 0
    prices_fixed: int = 0
    floors_filled: int = 0
    failed: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat() if self.started_at else None
        data["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        return data


_lock = threading.Lock()
_state = SweepState()


def get_state() -> dict:
    with _lock:
        return _state.to_dict()


def request_stop() -> bool:
    with _lock:
        if not _state.is_running:
            return False
        _state.stop_requested = True
        return True


def _active_olx_ids() -> list[int]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(Listing.id)
            .where(Listing.source == "olx", Listing.status == "active")
            .order_by(Listing.seen_at.asc())
        )
        return list(rows)


def start_sweep_in_background(delay_seconds: float = 0.7) -> bool:
    global _state
    with _lock:
        if _state.is_running:
            return False
        _state = SweepState(is_running=True, started_at=utcnow())

    threading.Thread(target=_worker, args=(delay_seconds,), daemon=True).start()
    return True


def _worker(delay_seconds: float) -> None:
    adapter = OlxAdapter()
    try:
        listing_ids = _active_olx_ids()
        with _lock:
            _state.total = len(listing_ids)
        with httpx.Client(timeout=25, follow_redirects=True, headers=_HEADERS) as client, \
                SessionLocal() as db:
            now = utcnow()
            for index, listing_id in enumerate(listing_ids, start=1):
                with _lock:
                    if _state.stop_requested:
                        break
                listing = db.get(Listing, listing_id)
                if listing is None or listing.status != "active":
                    continue
                try:
                    probe = adapter.probe_listing(listing.url, client)
                except Exception:  # network/parse hiccup — skip, don't abort
                    with _lock:
                        _state.failed += 1
                        _state.processed += 1
                    continue
                if probe.is_gone:
                    prev_price = listing.price_usd
                    listing.status = "removed"
                    listing.seen_at = now
                    db.add(
                        ListingEvent(
                            listing_id=listing.id,
                            event_type="delisted",
                            old_status="active",
                            new_status="removed",
                            old_price_usd=prev_price,
                            source="olx",
                            source_id=listing.source_id,
                            note="Detail-page sweep: ад в архиве/удалён",
                            at=now,
                        )
                    )
                    with _lock:
                        _state.archived += 1
                else:
                    if probe.photos and not _has_photos(listing.photos):
                        listing.photos = dumps_json(probe.photos)
                        with _lock:
                            _state.photos_filled += 1
                    if _apply_usd_price(listing, probe.usd_price, now):
                        with _lock:
                            _state.prices_fixed += 1
                    if _backfill_floor(listing, probe):
                        with _lock:
                            _state.floors_filled += 1
                with _lock:
                    _state.processed += 1
                if index % _COMMIT_EVERY == 0:
                    db.commit()
                time.sleep(delay_seconds)
            db.commit()
    except Exception as exc:  # pragma: no cover - background safety net
        with _lock:
            _state.last_error = str(exc)
    finally:
        with _lock:
            _state.is_running = False
            _state.finished_at = utcnow()


def _has_photos(raw: str | None) -> bool:
    return bool(raw) and raw not in ("[]", "")


def _backfill_floor(listing: Listing, probe) -> bool:
    """Fill floor / total_floors for rows the search-page ingest left as None.

    Floor is a physical property of the flat; the detail-page params are
    authoritative, so we only fill the gaps and never overwrite a known value.
    """
    changed = False
    if listing.floor is None and probe.floor is not None:
        listing.floor = probe.floor
        changed = True
    if listing.total_floors is None and probe.total_floors is not None:
        listing.total_floors = probe.total_floors
        changed = True
    return changed


def probe_one_listing(listing_id: int) -> dict:
    """Synchronously probe a single OLX listing's detail page and apply the
    у.е. price / photo fixes. Used to skip the full-sweep wait when a single
    row needs to be reconciled right now."""
    adapter = OlxAdapter()
    with httpx.Client(timeout=25, follow_redirects=True, headers=_HEADERS) as client, \
            SessionLocal() as db:
        listing = db.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "reason": "not_found"}
        if listing.source != "olx":
            return {"ok": False, "reason": "not_olx", "source": listing.source}
        try:
            probe = adapter.probe_listing(listing.url, client)
        except Exception as exc:  # noqa: BLE001 — surface the failure to the caller
            return {"ok": False, "reason": "probe_failed", "error": str(exc)}
        now = utcnow()
        result: dict = {
            "ok": True,
            "listing_id": listing.id,
            "url": listing.url,
            "is_gone": probe.is_gone,
            "price_before": listing.price_usd,
            "price_after": listing.price_usd,
            "floor": listing.floor,
            "applied_usd_price": False,
        }
        if probe.is_gone:
            listing.status = "removed"
            listing.seen_at = now
            db.commit()
            result["status"] = "removed"
            return result
        if probe.photos and not _has_photos(listing.photos):
            listing.photos = dumps_json(probe.photos)
            result["photos_filled"] = True
        if _apply_usd_price(listing, probe.usd_price, now):
            result["applied_usd_price"] = True
            result["price_after"] = listing.price_usd
        if _backfill_floor(listing, probe):
            result["floor_filled"] = True
            result["floor"] = listing.floor
        db.commit()
        return result


# Floor for "the у.е.-price is materially different from what we stored"
# decisions. ≥1% diff filters out rounding while still catching the 5–7%
# bias that the OLX-live-rate ↔ fixed-12 700-rate round trip introduces.
_PRICE_FIX_TOLERANCE = 0.01


def _apply_usd_price(listing: Listing, usd_price: float | None, now: datetime) -> bool:
    """Override the search-page-derived UZS→USD price with the seller's
    authoritative у.е. ask from the detail page.

    Search-page JSON-LD always reports UZS at OLX's live rate; we then divide
    by the fixed ``USD_TO_UZS``, so у.е.-priced ads come out 5–7% off. The
    detail page preserves the original currency, so when ``ListingProbe`` says
    "this ad is у.е.", trust that value and rewrite price / currency / ppm.
    Logs a ``price_changed`` event only on real drops (>0.2% — mirrors the
    upsert-time rule that filters out FX-noise and seller bumps).
    """
    if usd_price is None or usd_price <= 0:
        return False
    prev_usd = listing.price_usd
    if prev_usd is not None and abs(prev_usd - usd_price) / prev_usd < _PRICE_FIX_TOLERANCE:
        return False
    listing.price = usd_price
    listing.currency = "USD"
    listing.price_usd = usd_price
    if listing.area_m2 and listing.area_m2 > 0:
        listing.price_per_m2_usd = round(usd_price / listing.area_m2, 2)
    session = object_session(listing)
    if (
        session is not None
        and prev_usd is not None
        and usd_price < prev_usd
        and (prev_usd - usd_price) / prev_usd > 0.002
    ):
        session.add(
            ListingEvent(
                listing_id=listing.id,
                event_type="price_changed",
                old_price_usd=prev_usd,
                new_price_usd=usd_price,
                source="olx",
                source_id=listing.source_id,
                note="Detail-page sweep: у.е.-цена уточнена с продавцом",
                at=now,
            )
        )
    return True
