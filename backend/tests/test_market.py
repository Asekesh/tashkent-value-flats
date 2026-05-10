from app.scrapers.base import RawListing
from app.services.listings import upsert_raw_listing
from app.services.market import estimate_market
from app.services.normalization import normalize_building_key


def test_building_average_and_savings(db_session):
    # Two listings in the same building with price_per_m2 = 1200
    first = RawListing(
        source="test",
        source_id="b1",
        url="https://test.local/b1",
        title="Flat A",
        price=120000,
        currency="USD",
        area_m2=100,
        rooms=2,
        district="Test District",
        address_raw="Building 1",
    )
    second = RawListing(
        source="test",
        source_id="b2",
        url="https://test.local/b2",
        title="Flat B",
        price=96000,
        currency="USD",
        area_m2=80,
        rooms=2,
        district="Test District",
        address_raw="Building 1",
    )

    l1, _ = upsert_raw_listing(db_session, first)
    l2, _ = upsert_raw_listing(db_session, second)
    db_session.commit()

    building_key = normalize_building_key("Test District", "Building 1")

    estimate = estimate_market(
        db_session,
        district="Test District",
        rooms=2,
        area_m2=120,
        building_key=building_key,
        listing_price_per_m2=900,
    )

    assert estimate.sample_size == 2
    assert estimate.market_price_per_m2_usd == 1200.0
    assert estimate.discount_percent == 25.0
    assert estimate.savings_usd == 36000.0
    assert estimate.is_below_market is True
