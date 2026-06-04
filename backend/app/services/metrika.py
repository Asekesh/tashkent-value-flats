"""Чтение посещаемости из Яндекс.Метрики (Stat API v1) для блока «Сайт» в /admin.

Счётчик уже стоит в index.html и считает всех (аноним + авторизованные). Здесь
только читаем агрегаты по OAuth-токену. Внешний API медленный (сотни мс) и
лимитируется → кэшируем весь ответ на CACHE_TTL. Любая ошибка/нет токена →
{"configured": False}: дашборд показывает «не настроено», а не падает.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger("app.metrika")

_API = "https://api-metrika.yandex.net/stat/v1/data"
CACHE_TTL_SECONDS = 600
_SUMMARY_METRICS = "ym:s:users,ym:s:visits,ym:s:pageviews,ym:s:bounceRate,ym:s:pageDepth"

_cache: dict[str, Any] = {"at": None, "data": None}


def _request(client: httpx.Client, token: str, counter: str, params: dict[str, str]) -> Optional[dict]:
    resp = client.get(
        _API,
        params={"ids": counter, **params},
        headers={"Authorization": f"OAuth {token}"},
        timeout=8.0,
    )
    resp.raise_for_status()
    return resp.json()


def _summary(client: httpx.Client, token: str, counter: str, date1: str) -> dict[str, Any]:
    """Тоталы метрик за период date1..today. totals[i] идёт в порядке метрик."""
    data = _request(
        client, token, counter,
        {"metrics": _SUMMARY_METRICS, "date1": date1, "date2": "today"},
    )
    totals = (data or {}).get("totals") or [0, 0, 0, 0, 0]
    return {
        "users": int(totals[0]),
        "visits": int(totals[1]),
        "pageviews": int(totals[2]),
        "bounce_rate": round(totals[3], 1),
        "page_depth": round(totals[4], 1),
    }


def _top_sources(client: httpx.Client, token: str, counter: str) -> list[dict[str, Any]]:
    data = _request(
        client, token, counter,
        {
            "metrics": "ym:s:visits",
            "dimensions": "ym:s:lastTrafficSource",
            "date1": "30daysAgo",
            "date2": "today",
            "sort": "-ym:s:visits",
            "limit": "6",
        },
    )
    rows: list[dict[str, Any]] = []
    for row in (data or {}).get("data", []):
        name = (row.get("dimensions") or [{}])[0].get("name") or "—"
        visits = int((row.get("metrics") or [0])[0])
        rows.append({"source": name, "visits": visits})
    return rows


def site_metrics() -> dict[str, Any]:
    """Сводка посещаемости: today / 7д / 30д + топ источников. Кэш 10 мин."""
    settings = get_settings()
    token = settings.yandex_metrika_oauth_token.strip()
    counter = settings.yandex_metrika_counter_id.strip()
    if not token or not counter:
        return {"configured": False}

    now = datetime.utcnow()
    cached = _cache["data"]
    if cached is not None and _cache["at"] is not None:
        if (now - _cache["at"]).total_seconds() < CACHE_TTL_SECONDS:
            return cached

    try:
        with httpx.Client() as client:
            result = {
                "configured": True,
                "counter_id": counter,
                "today": _summary(client, token, counter, "today"),
                "week": _summary(client, token, counter, "7daysAgo"),
                "month": _summary(client, token, counter, "30daysAgo"),
                "sources": _top_sources(client, token, counter),
            }
    except Exception as exc:  # noqa: BLE001 — дашборд не должен падать из-за внешнего API
        logger.warning("Yandex Metrika fetch failed: %s", exc)
        # Отдаём прошлый кэш, если был — лучше слегка устаревшие цифры, чем дыра.
        if cached is not None:
            return cached
        return {"configured": True, "error": True}

    _cache["data"] = result
    _cache["at"] = now
    return result
