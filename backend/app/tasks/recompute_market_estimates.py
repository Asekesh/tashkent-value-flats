"""Батч-пересчёт оценки рынка для всех активных листингов.

Запуск:
    python -m app.tasks.recompute_market_estimates

Используется для разовой миграции после добавления столбцов market_*
и для ночного rebuild'а (см. scheduler.py — там вызывается после полного
скрейп-цикла).
"""
from __future__ import annotations

import sys
import time

from app.db.session import SessionLocal
from app.services.market_estimate import recompute_all


def main() -> int:
    t0 = time.perf_counter()

    def _progress(n: int) -> None:
        dt = time.perf_counter() - t0
        print(f"  ... {n} обработано за {dt:.1f}с", flush=True)

    with SessionLocal() as db:
        total = recompute_all(db, on_progress=_progress)
    dt = time.perf_counter() - t0
    print(f"готово: {total} листингов за {dt:.1f}с", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
