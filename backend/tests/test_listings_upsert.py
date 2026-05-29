from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.models import Listing, ListingEvent
from app.scrapers.base import RawListing
from app.services.listings import upsert_raw_listing
from app.services.scrape import _run_live_scan


def _raw_olx_card(*, price: float, title: str = "NRG Meros") -> RawListing:
    return RawListing(
        source="olx",
        source_id="ID4nNtY",
        url="https://www.olx.uz/d/obyavlenie/nrg-meros-novostroyka-mirabadskiy-rayon-ID4nNtY.html",
        title=title,
        price=price,
        currency="UZS",
        area_m2=50,
        rooms=2,
        district="Мирабадский район",
        address_raw="NRG Meros",
        floor=12,
        total_floors=13,
        description="Новостройка",
    )


def test_olx_search_refresh_preserves_detail_verified_usd_price(db_session):
    listing, is_new = upsert_raw_listing(db_session, _raw_olx_card(price=1_016_000_000))
    assert is_new is True

    # Simulate archive_sweep/probe fixing the seller's authoritative у.е. ask:
    # OLX search card value is ~80k after UZS->USD conversion, detail page is 85k.
    listing.price = 85_000
    listing.currency = "USD"
    listing.price_usd = 85_000
    listing.price_per_m2_usd = 1_700
    db_session.commit()

    refreshed, is_new = upsert_raw_listing(
        db_session,
        _raw_olx_card(price=1_016_000_000, title="NRG Meros updated"),
    )
    db_session.commit()

    assert is_new is False
    assert refreshed.id == listing.id
    assert refreshed.title == "NRG Meros updated"
    assert refreshed.currency == "USD"
    assert refreshed.price == 85_000
    assert refreshed.price_usd == 85_000
    assert refreshed.price_per_m2_usd == 1_700

    events = db_session.scalars(select(ListingEvent).where(ListingEvent.listing_id == listing.id)).all()
    assert [event.event_type for event in events] == ["first_seen"]
    assert db_session.scalar(select(Listing.price_usd).where(Listing.id == listing.id)) == 85_000


def test_olx_search_refresh_preserves_usd_even_outside_fx_window(db_session):
    """A search-page UZS card must never overwrite a detail-confirmed USD ask,
    regardless of how far the fixed-rate estimate drifts — upsert alone never
    rolls back. (Real changes are re-probed in the live scan, not here.)"""
    listing, _ = upsert_raw_listing(db_session, _raw_olx_card(price=1_016_000_000))
    listing.price = 85_000
    listing.currency = "USD"
    listing.price_usd = 85_000
    listing.price_per_m2_usd = 1_700
    db_session.commit()

    # 939_900_000 UZS -> ~74_008 USD, ratio ~0.87 — outside the old [0.90,1.02]
    # window that used to let this roll the price back down.
    refreshed, is_new = upsert_raw_listing(db_session, _raw_olx_card(price=939_900_000))
    db_session.commit()

    assert is_new is False
    assert refreshed.currency == "USD"
    assert refreshed.price == 85_000
    assert refreshed.price_usd == 85_000
    assert refreshed.price_per_m2_usd == 1_700
    events = db_session.scalars(select(ListingEvent).where(ListingEvent.listing_id == listing.id)).all()
    assert [event.event_type for event in events] == ["first_seen"]


class _FakeOlxAdapter:
    source = "olx"

    def __init__(self, cards, *, probe=None, probe_exc=None):
        self._cards = cards
        self._probe = probe
        self._probe_exc = probe_exc
        self.probed_urls: list[str] = []

    def fetch_live_pages(self, max_pages=None, delay_seconds=0):
        yield self._cards

    def probe_listing(self, url, client):
        self.probed_urls.append(url)
        if self._probe_exc is not None:
            raise self._probe_exc
        return self._probe


def _run_quick(db, adapter):
    return _run_live_scan(
        db,
        adapter,
        mode="quick",
        max_pages=1,
        delay_seconds=0,
        quick_known_stop_threshold=50,
        min_price_usd=5_000,
        min_price_per_m2_usd=100,
    )


def _seed_usd_listing(db):
    listing, _ = upsert_raw_listing(db, _raw_olx_card(price=1_016_000_000))
    listing.price = 85_000
    listing.currency = "USD"
    listing.price_usd = 85_000
    listing.price_per_m2_usd = 1_700
    db.commit()
    return listing


def test_known_olx_reprobes_detail_on_real_price_drop(db_session):
    """Search price drops out of the FX-noise window -> re-probe the detail
    page and update to the TRUE new USD ask with a correct price_changed."""
    listing = _seed_usd_listing(db_session)
    # 939_900_000 UZS -> ~74_008 USD (ratio ~0.87) triggers the re-probe; the
    # detail page reports the seller's real new ask of 78_000 (an 8.2% drop).
    adapter = _FakeOlxAdapter(
        [_raw_olx_card(price=939_900_000)],
        probe=SimpleNamespace(is_gone=False, usd_price=78_000.0, photos=[], floor=12, total_floors=13),
    )

    new_count, updated_count = _run_quick(db_session, adapter)

    db_session.refresh(listing)
    assert (new_count, updated_count) == (0, 1)
    assert adapter.probed_urls == [_raw_olx_card(price=1).url]
    assert listing.currency == "USD"
    assert listing.price == 78_000
    assert listing.price_usd == 78_000
    assert listing.price_per_m2_usd == 78_000 / 50
    events = db_session.scalars(select(ListingEvent).where(ListingEvent.listing_id == listing.id)).all()
    assert [e.event_type for e in events] == ["first_seen", "price_changed"]
    drop = next(e for e in events if e.event_type == "price_changed")
    assert (drop.old_price_usd, drop.new_price_usd) == (85_000, 78_000)


def test_known_olx_reprobe_failure_keeps_usd_no_rollback(db_session):
    """If the detail re-probe fails, the search-UZS estimate must NOT overwrite
    the stored USD — no rollback, no bogus event."""
    listing = _seed_usd_listing(db_session)
    adapter = _FakeOlxAdapter(
        [_raw_olx_card(price=939_900_000)],
        probe_exc=RuntimeError("detail page timeout"),
    )

    _run_quick(db_session, adapter)

    db_session.refresh(listing)
    assert adapter.probed_urls == [_raw_olx_card(price=1).url]  # re-probe was attempted
    assert listing.currency == "USD"
    assert listing.price == 85_000
    assert listing.price_usd == 85_000
    events = db_session.scalars(select(ListingEvent).where(ListingEvent.listing_id == listing.id)).all()
    assert [e.event_type for e in events] == ["first_seen"]


def test_known_olx_within_fx_window_skips_reprobe(db_session):
    """In-window search refresh is fixed-rate FX noise: no HTTP probe, price
    held by the upsert preserve guard."""
    listing = _seed_usd_listing(db_session)
    # 1_016_000_000 UZS -> ~80_000 USD, ratio ~0.94 — inside the window.
    adapter = _FakeOlxAdapter(
        [_raw_olx_card(price=1_016_000_000)],
        probe=SimpleNamespace(is_gone=False, usd_price=999.0, photos=[], floor=12, total_floors=13),
    )

    _run_quick(db_session, adapter)

    db_session.refresh(listing)
    assert adapter.probed_urls == []  # FX-noise window -> no detail probe
    assert listing.currency == "USD"
    assert listing.price_usd == 85_000


def test_new_olx_live_scan_uses_detail_price_before_insert(db_session):
    class FakeOlxAdapter:
        source = "olx"

        def __init__(self):
            self.probed_urls: list[str] = []

        def fetch_live_pages(self, max_pages=None, delay_seconds=0):
            yield [_raw_olx_card(price=1_016_000_000)]

        def probe_listing(self, url, client):
            self.probed_urls.append(url)
            return SimpleNamespace(
                is_gone=False,
                usd_price=85_000.0,
                photos=["https://img.test/flat.jpg"],
                floor=12,
                total_floors=13,
            )

    adapter = FakeOlxAdapter()

    new_count, updated_count = _run_live_scan(
        db_session,
        adapter,
        mode="quick",
        max_pages=1,
        delay_seconds=0,
        quick_known_stop_threshold=50,
        min_price_usd=5_000,
        min_price_per_m2_usd=100,
    )

    listing = db_session.scalar(select(Listing).where(Listing.source == "olx", Listing.source_id == "ID4nNtY"))
    assert (new_count, updated_count) == (1, 0)
    assert adapter.probed_urls == [_raw_olx_card(price=1).url]
    assert listing.currency == "USD"
    assert listing.price == 85_000
    assert listing.price_usd == 85_000
    assert listing.price_per_m2_usd == 1_700
