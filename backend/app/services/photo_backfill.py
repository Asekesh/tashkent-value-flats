"""Detail-page photo backfill for OLX.

OLX search only exposes 25 pages, so listings that scroll past that window
can no longer be reached via the listing pages — but their detail pages stay
live by direct URL. This walks active OLX listings that have no photos, pulls
the photos straight from each detail page, and delists the ones that 404.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime

import httpx
from sqlalchemy import or_, select

from app.db.session import SessionLocal
from app.models import Listing
from app.scrapers.adapters.olx import OlxAdapter
from app.services.normalization import dumps_json, utcnow

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TashkentValueFlats/0.1; +https://github.com/Asekesh/tashkent-value-flats)",
    "Accept-Language": "ru,en;q=0.8",
}
_COMMIT_EVERY = 25


@dataclass
class BackfillState:
    is_running: bool = False
    stop_requested: bool = False
    total: int = 0
    processed: int = 0
    filled: int = 0
    removed: int = 0
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
_state = BackfillState()


def get_state() -> dict:
    with _lock:
        return _state.to_dict()


def request_stop() -> bool:
    with _lock:
        if not _state.is_running:
            return False
        _state.stop_requested = True
        return True


def _photoless_olx_ids() -> list[int]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(Listing.id)
            .where(
                Listing.source == "olx",
                Listing.status == "active",
                or_(Listing.photos == "[]", Listing.photos == "", Listing.photos.is_(None)),
            )
            .order_by(Listing.seen_at.desc())
        )
        return list(rows)


def start_photo_backfill_in_background(delay_seconds: float = 0.7) -> bool:
    global _state
    with _lock:
        if _state.is_running:
            return False
        _state = BackfillState(is_running=True, started_at=utcnow())

    def _worker() -> None:
        adapter = OlxAdapter()
        try:
            listing_ids = _photoless_olx_ids()
            with _lock:
                _state.total = len(listing_ids)
            with httpx.Client(timeout=25, follow_redirects=True, headers=_HEADERS) as client, \
                    SessionLocal() as db:
                for index, listing_id in enumerate(listing_ids, start=1):
                    with _lock:
                        if _state.stop_requested:
                            break
                    listing = db.get(Listing, listing_id)
                    if listing is None:
                        continue
                    try:
                        photos = adapter.fetch_listing_photos(listing.url, client)
                    except Exception:  # network/parse hiccup — skip, don't abort
                        with _lock:
                            _state.failed += 1
                            _state.processed += 1
                        continue
                    if photos is None:
                        listing.status = "removed"
                        listing.seen_at = utcnow()
                        with _lock:
                            _state.removed += 1
                    elif photos:
                        listing.photos = dumps_json(photos)
                        with _lock:
                            _state.filled += 1
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

    threading.Thread(target=_worker, daemon=True).start()
    return True
