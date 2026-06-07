"""Manual full recompute of cached market estimates.

Each upsert recomputes the changed listing, and a weekly loop rebuilds
everyone — but after a CMA-logic change the stored estimates
(market_price_per_m2_usd / discount_percent / is_below_market) stay stale
until that weekly pass, which on top of that resets its timer on every
deploy. This lets an admin trigger the server-side rebuild on demand
(minutes over the internal DB) instead of waiting up to a week.

Triggered via POST /api/admin/market/recompute; progress at
GET /api/admin/market/recompute/progress.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Listing
from app.services.market_estimate import recompute_all
from app.services.normalization import utcnow


@dataclass
class RecomputeState:
    is_running: bool = False
    total: int = 0
    processed: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat() if self.started_at else None
        data["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        return data


_lock = threading.Lock()
_state = RecomputeState()


def get_state() -> dict:
    with _lock:
        return _state.to_dict()


def start_market_recompute_in_background() -> bool:
    global _state
    with _lock:
        if _state.is_running:
            return False
        _state = RecomputeState(is_running=True, started_at=utcnow())

    def _worker() -> None:
        try:
            with SessionLocal() as db:
                total = db.scalar(
                    select(func.count()).select_from(Listing).where(Listing.status == "active")
                )
                with _lock:
                    _state.total = int(total or 0)

                def _progress(n: int) -> None:
                    with _lock:
                        _state.processed = n

                recompute_all(db, on_progress=_progress)
        except Exception as exc:  # pragma: no cover - background safety net
            with _lock:
                _state.last_error = str(exc)
        finally:
            with _lock:
                _state.is_running = False
                _state.finished_at = utcnow()

    threading.Thread(target=_worker, daemon=True).start()
    return True
