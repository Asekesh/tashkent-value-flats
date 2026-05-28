from __future__ import annotations

from datetime import datetime, timedelta

from app.models import Listing
from app.services.dedup import merge_existing_duplicates
from app.services.normalization import dumps_json


def _make_listing(
    *,
    source: str,
    source_id: str,
    price: float = 90000,
    price_usd: float = 7000.0,
    area_m2: float = 60,
    floor: int | None = 3,
    total_floors: int | None = 9,
    seen_at: datetime,
    status: str = "active",
    source_urls: list[dict] | None = None,
) -> Listing:
    return Listing(
        source=source,
        source_id=source_id,
        url=f"https://{source}.test/{source_id}",
        title="Flat",
        price=price,
        currency="UZS",
        price_usd=price_usd,
        area_m2=area_m2,
        price_per_m2_usd=117.0,
        rooms=2,
        floor=floor,
        total_floors=total_floors,
        district="Мирабадский район",
        address_raw="Дом 12",
        building_key="мирабадский район::дом 12",
        description=None,
        photos="[]",
        seller_type=None,
        seen_at=seen_at,
        status=status,
        duplicate_group_key=f"key-{source_id}",
        duplicate_count=1,
        source_urls=dumps_json(source_urls or [{"source": source, "url": f"https://{source}.test/{source_id}"}]),
    )


def test_merge_existing_duplicates_keeps_newest_active_and_merges_urls(db_session):
    now = datetime.utcnow()
    older = _make_listing(source="olx", source_id="4kJlt", seen_at=now - timedelta(hours=2))
    newer = _make_listing(source="olx", source_id="64046215", seen_at=now)
    different = _make_listing(source="olx", source_id="9aBcD", price=95000, price_usd=140000.0, seen_at=now)
    db_session.add_all([older, newer, different])
    db_session.commit()

    result = merge_existing_duplicates(db_session)

    assert result["merged_groups"] == 1
    assert result["deleted_rows"] == 1
    remaining = {l.source_id for l in db_session.query(Listing).all()}
    assert remaining == {"64046215", "9aBcD"}
    survivor = db_session.query(Listing).filter_by(source_id="64046215").one()
    assert survivor.duplicate_count == 2


def test_merge_existing_duplicates_prefers_active_over_removed(db_session):
    now = datetime.utcnow()
    removed_recent = _make_listing(source="olx", source_id="64046215", seen_at=now, status="removed")
    active_older = _make_listing(source="olx", source_id="4kJlt", seen_at=now - timedelta(hours=1))
    db_session.add_all([removed_recent, active_older])
    db_session.commit()

    merge_existing_duplicates(db_session)

    survivors = db_session.query(Listing).all()
    assert len(survivors) == 1
    assert survivors[0].source_id == "4kJlt"


def test_merge_existing_duplicates_collapses_price_cluster(db_session):
    # Three reposts of the same flat priced $99k / $99.2k / $100k — within 5%
    # of each other, same floor/total_floors. The current price-bucket
    # fingerprint never matches them, so only the loose pass cleans them up.
    now = datetime.utcnow()
    db_session.add_all([
        _make_listing(source="olx", source_id="3988", price=1, price_usd=99012.52, seen_at=now - timedelta(hours=3)),
        _make_listing(source="olx", source_id="11290", price=2, price_usd=99191.93, seen_at=now - timedelta(hours=2)),
        _make_listing(source="olx", source_id="13057", price=3, price_usd=100104.06, seen_at=now - timedelta(hours=1)),
    ])
    db_session.commit()

    result = merge_existing_duplicates(db_session)

    assert result["merged_groups"] == 1
    assert result["deleted_rows"] == 2
    remaining = db_session.query(Listing).all()
    assert len(remaining) == 1
    # Cheapest active row survives — the panel surfaces the best deal per flat.
    assert remaining[0].source_id == "3988"
    assert remaining[0].duplicate_count == 3


def test_merge_existing_duplicates_skips_far_apart_prices(db_session):
    # Same building/floor but $80k vs $100k → +25% gap, different flats; do
    # not merge.
    now = datetime.utcnow()
    db_session.add_all([
        _make_listing(source="olx", source_id="cheap", price=1, price_usd=80000.0, seen_at=now),
        _make_listing(source="olx", source_id="dear", price=2, price_usd=100000.0, seen_at=now),
    ])
    db_session.commit()

    result = merge_existing_duplicates(db_session)

    assert result["merged_groups"] == 0
    assert result["deleted_rows"] == 0
    assert db_session.query(Listing).count() == 2


def test_merge_existing_duplicates_merges_none_floor_with_known(db_session):
    # Same flat reposted three times: one card has the floor, two lost it.
    # The old pass-2 gate dropped the None-floor rows before clustering, so
    # they survived as visible dupes (the Akai City case in prod).
    now = datetime.utcnow()
    db_session.add_all([
        _make_listing(source="olx", source_id="with-floor", price=1, price_usd=240664.0, floor=18, total_floors=22, seen_at=now - timedelta(hours=3)),
        _make_listing(source="olx", source_id="no-floor-a", price=2, price_usd=236587.0, floor=None, total_floors=None, seen_at=now - timedelta(hours=2)),
        _make_listing(source="olx", source_id="no-floor-b", price=3, price_usd=236587.0, floor=None, total_floors=None, seen_at=now - timedelta(hours=1)),
    ])
    db_session.commit()

    result = merge_existing_duplicates(db_session)

    # Pass 1 collapses the two identical-price None-floor rows; pass 2 then
    # folds the survivor in with the priced-$240k row (single known floor,
    # None is wildcarded).
    assert result["deleted_rows"] == 2
    remaining = db_session.query(Listing).all()
    assert len(remaining) == 1
    # Cheapest survives — best deal for the same flat. Pass 1 keeps the
    # more recently seen of the two identical $236,587 rows, then pass 2
    # picks the cheapest from {that survivor, $240,664 with-floor row}.
    assert remaining[0].source_id == "no-floor-b"


def test_merge_existing_duplicates_keeps_distinct_known_floors_apart(db_session):
    # Same building/area but two genuinely different flats on floors 3 and 9,
    # both priced inside the ±5% window. Must stay separate.
    now = datetime.utcnow()
    db_session.add_all([
        _make_listing(source="olx", source_id="f3", price=1, price_usd=99000.0, floor=3, total_floors=9, seen_at=now),
        _make_listing(source="olx", source_id="f9", price=2, price_usd=100000.0, floor=9, total_floors=9, seen_at=now),
    ])
    db_session.commit()

    result = merge_existing_duplicates(db_session)

    assert result["merged_groups"] == 0
    assert db_session.query(Listing).count() == 2


def test_merge_existing_duplicates_dry_run_changes_nothing(db_session):
    now = datetime.utcnow()
    db_session.add_all([
        _make_listing(source="olx", source_id="a", seen_at=now),
        _make_listing(source="olx", source_id="b", seen_at=now - timedelta(hours=1)),
    ])
    db_session.commit()

    result = merge_existing_duplicates(db_session, dry_run=True)

    assert result["merged_groups"] == 1
    assert result["deleted_rows"] == 1
    assert db_session.query(Listing).count() == 2
