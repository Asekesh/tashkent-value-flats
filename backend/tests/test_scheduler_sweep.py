from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import scheduler


def _settings(**over):
    base = dict(
        allow_live_scraping=True,
        olx_sweep_startup_delay_seconds=0,
        olx_sweep_interval_hours=12,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_maybe_start_olx_sweep_triggers_when_active(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "_has_active_olx", lambda: True)
    monkeypatch.setattr(
        scheduler.archive_sweep, "start_sweep_in_background", lambda: calls.append(1) or True
    )
    assert scheduler._maybe_start_olx_sweep() is True
    assert calls == [1]


def test_maybe_start_olx_sweep_skips_when_no_active(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "_has_active_olx", lambda: False)
    monkeypatch.setattr(
        scheduler.archive_sweep, "start_sweep_in_background", lambda: calls.append(1) or True
    )
    assert scheduler._maybe_start_olx_sweep() is False
    assert calls == []


def test_sweep_loop_skipped_when_live_disabled(monkeypatch):
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings(allow_live_scraping=False))
    triggers = []
    monkeypatch.setattr(scheduler, "_maybe_start_olx_sweep", lambda: triggers.append(1))
    asyncio.run(scheduler.scheduled_olx_startup_sweep())
    assert triggers == []


def test_sweep_loop_single_pass_when_interval_zero(monkeypatch):
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings(olx_sweep_interval_hours=0))
    triggers = []
    monkeypatch.setattr(scheduler, "_maybe_start_olx_sweep", lambda: triggers.append(1))
    asyncio.run(scheduler.scheduled_olx_startup_sweep())
    assert triggers == [1]  # стартовый проход и ничего больше — цикла нет


def test_sweep_loop_repeats_on_interval(monkeypatch):
    monkeypatch.setattr(scheduler, "get_settings", lambda: _settings(olx_sweep_interval_hours=12))
    triggers = []
    monkeypatch.setattr(scheduler, "_maybe_start_olx_sweep", lambda: triggers.append(1))

    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:  # стартовая задержка + 2 интервала -> рвём цикл
            raise asyncio.CancelledError

    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scheduler.scheduled_olx_startup_sweep())

    assert sleeps[0] == 0  # startup delay
    assert sleeps[1] == 12 * 3600  # первый интервал
    assert sleeps[2] == 12 * 3600  # второй интервал
    # стартовый проход + минимум один периодический
    assert len(triggers) >= 2
