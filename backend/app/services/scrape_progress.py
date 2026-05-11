from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ScrapeProgressState:
    is_running: bool = False
    task_id: Optional[int] = None
    mode: str = ""
    sources: list[str] = field(default_factory=list)
    current_source: Optional[str] = None
    pages_scanned: int = 0
    found_total: int = 0
    new_total: int = 0
    updated_total: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "is_running": self.is_running,
            "task_id": self.task_id,
            "mode": self.mode,
            "sources": self.sources,
            "current_source": self.current_source,
            "pages_scanned": self.pages_scanned,
            "found_total": self.found_total,
            "new_total": self.new_total,
            "updated_total": self.updated_total,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "last_error": self.last_error,
        }


_lock = threading.Lock()
_state = ScrapeProgressState()


def get_state() -> dict:
    with _lock:
        return _state.to_dict()


def start(mode: str, sources: list[str]) -> bool:
    global _state
    with _lock:
        if _state.is_running:
            return False
        _state = ScrapeProgressState(
            is_running=True,
            mode=mode,
            sources=list(sources),
            started_at=datetime.utcnow(),
        )
        return True


def set_task_id(task_id: int) -> None:
    with _lock:
        _state.task_id = task_id


def set_current_source(source: str) -> None:
    with _lock:
        _state.current_source = source


def increment(*, pages: int = 0, found: int = 0, new: int = 0, updated: int = 0) -> None:
    with _lock:
        _state.pages_scanned += pages
        _state.found_total += found
        _state.new_total += new
        _state.updated_total += updated


def finish(error: Optional[str] = None) -> None:
    with _lock:
        _state.is_running = False
        _state.finished_at = datetime.utcnow()
        _state.current_source = None
        if error:
            _state.last_error = error
