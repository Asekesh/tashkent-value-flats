from app.models import Listing
from app.scrapers.base import RawListing
from app.services.listings import upsert_raw_listing
from app.services.market_estimate import estimate_for_listing, recompute_all


def _seed(db, source_id, area, price, address="Чехова 5", title=None, district="Test District"):
    raw = RawListing(
        source="test",
        source_id=source_id,
        url=f"https://test.local/{source_id}",
        title=title or f"2-комн {source_id}",
        price=price,
        currency="USD",
        area_m2=area,
        rooms=2,
        district=district,
        address_raw=address,
        floor=5,
        total_floors=9,
    )
    listing, _ = upsert_raw_listing(db, raw)
    return listing


def test_estimate_uses_building_tier_when_peers_in_same_building(db_session):
    subject = _seed(db_session, "e1", area=100, price=80_000)
    _seed(db_session, "e2", area=98, price=100_000)
    _seed(db_session, "e3", area=102, price=105_000)
    db_session.commit()

    estimate = estimate_for_listing(db_session, subject)
    assert estimate.basis == "building"
    assert estimate.sample_size == 2
    assert estimate.market_price_per_m2_usd is not None
    # subject 800 $/м², рынок ~1020 $/м² → дисконт ~20%
    assert estimate.discount_percent is not None
    assert estimate.discount_percent > 15


def test_estimate_no_discount_for_extreme_floor(db_session):
    # subject на 1-м этаже — для крайних этажей дисконт не считаем
    raw = RawListing(
        source="test",
        source_id="ex1",
        url="https://test.local/ex1",
        title="2-комн",
        price=80_000,
        currency="USD",
        area_m2=100,
        rooms=2,
        district="Test District",
        address_raw="Чехова 5",
        floor=1,
        total_floors=9,
    )
    subject, _ = upsert_raw_listing(db_session, raw)
    _seed(db_session, "ex2", area=98, price=100_000)
    _seed(db_session, "ex3", area=102, price=105_000)
    db_session.commit()

    estimate = estimate_for_listing(db_session, subject)
    assert estimate.discount_percent is None
    assert estimate.is_below_market is False


def test_recompute_all_fixes_first_listing_after_peers_arrive(db_session):
    """Первый листинг при upsert не видит соседей — у него
    market_basis=insufficient_data. После recompute_all он уже видит
    остальных и получает нормальный basis."""
    subject = _seed(db_session, "r1", area=100, price=80_000)
    _seed(db_session, "r2", area=98, price=100_000)
    _seed(db_session, "r3", area=102, price=105_000)
    db_session.commit()

    # subject был добавлен первым → его estimate посчитан без соседей
    db_session.refresh(subject)
    assert subject.market_basis == "insufficient_data"

    recompute_all(db_session)
    db_session.refresh(subject)
    assert subject.market_basis == "building"
    assert subject.discount_percent is not None
    assert subject.is_below_market is True  # ~20% дисконта


def test_estimate_stored_to_columns_on_upsert(db_session):
    subject = _seed(db_session, "s1", area=100, price=80_000)
    _seed(db_session, "s2", area=98, price=100_000)
    _seed(db_session, "s3", area=102, price=105_000)
    db_session.commit()
    recompute_all(db_session)

    fresh = db_session.get(Listing, subject.id)
    assert fresh.market_calculated_at is not None
    assert fresh.market_price_per_m2_usd is not None
    assert fresh.market_basis == "building"
