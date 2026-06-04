"""Лёгкие метрики здоровья процесса в памяти: латенси, RPM, конкурентность.

Без Prometheus и внешних зависимостей — кольцевой буфер последних запросов
(момент + длительность) под локом. Живёт до рестарта процесса, чего для вопроса
«тормозит ли прямо сейчас и есть ли запас» достаточно. Один uvicorn-воркер =
одна копия чисел, межпроцессная агрегация не нужна. Перцентили/RPM считаем по
окну в 5 минут; пик in-flight копится с момента старта.

Используем time.monotonic() — не зависит от перевода часов; CPython GIL делает
inc/dec int практически атомарными, но лок берём явно ради корректного пика.
"""
from __future__ import annotations

import threading
import time
from collections import deque

_WINDOW_SECONDS = 300  # окно для p50/p95
_MAXLEN = 5000  # потолок буфера — ~16 запросов/сек × 5 мин

_lock = threading.Lock()
_samples: deque[tuple[float, float]] = deque(maxlen=_MAXLEN)  # (monotonic_ts, ms)
_inflight = 0
_peak_inflight = 0


def inc() -> None:
    global _inflight, _peak_inflight
    with _lock:
        _inflight += 1
        if _inflight > _peak_inflight:
            _peak_inflight = _inflight


def dec() -> None:
    global _inflight
    with _lock:
        _inflight = max(_inflight - 1, 0)


def record(duration_ms: float) -> None:
    with _lock:
        _samples.append((time.monotonic(), duration_ms))


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
    return round(sorted_vals[k], 1)


def snapshot() -> dict[str, float | int]:
    now = time.monotonic()
    with _lock:
        samples = list(_samples)
        inflight = _inflight
        peak = _peak_inflight
    durs = sorted(d for (ts, d) in samples if now - ts <= _WINDOW_SECONDS)
    rpm = sum(1 for (ts, _) in samples if now - ts <= 60)
    return {
        "p50_ms": _percentile(durs, 50),
        "p95_ms": _percentile(durs, 95),
        "rpm": rpm,
        "inflight": inflight,
        "peak_inflight": peak,
        "window_samples": len(durs),
    }


def pool_stats(engine) -> dict[str, int]:
    """Статистика пула соединений SQLAlchemy. Для sqlite-пулов (dev) часть
    методов отсутствует — тогда возвращаем пустой словарь, шаблон это переживёт."""
    pool = engine.pool
    # Только QueuePool (Postgres) даёт size()/checkedout() как методы. У sqlite-
    # пулов (dev/тесты) этих методов нет либо size — int-атрибут → TypeError.
    try:
        size = pool.size()
        checked_out = pool.checkedout()
        max_overflow = max(getattr(pool, "_max_overflow", 0), 0)
    except (AttributeError, TypeError):
        return {}
    capacity = size + max_overflow
    return {
        "checked_out": checked_out,
        "size": size,
        "max_overflow": max_overflow,
        "capacity": capacity,
        "available": max(capacity - checked_out, 0),
    }
