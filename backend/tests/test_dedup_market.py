from app.scrapers.base import RawListing
from app.scrapers.registry import parse_fixture
from app.services.listings import upsert_raw_listing
from app.services.market import estimate_market
from app.services.normalization import normalize_building_key


def test_duplicate_listing_merges_source_urls(db_session):
    first = RawListing(
        source="olx",
        source_id="same-flat-olx",
        url="https://olx.test/same",
        title="Same flat",
        price=90000,
        currency="USD",
        area_m2=60,
        rooms=2,
        district="Мирабадский район",
        address_raw="Садык Азимова 12",
    )
    second = RawListing(
        source="uybor",
        source_id="same-flat-uybor",
        url="https://uybor.test/same",
        title="Same flat duplicate",
        price=90500,
        currency="USD",
        area_m2=60.5,
        rooms=2,
        district="Мирабадский район",
        address_raw="Садык Азимова 12",
    )

    listing, is_new = upsert_raw_listing(db_session, first)
    assert is_new is True
    duplicate, is_new = upsert_raw_listing(db_session, second)
    db_session.commit()

    assert is_new is False
    assert duplicate.id == listing.id
    assert duplicate.duplicate_count == 2


def test_market_estimate_prefers_building_and_flags_15_percent_discount(db_session):
    for source in ["olx", "uybor", "realt24"]:
        for raw in parse_fixture(source):
            upsert_raw_listing(db_session, raw)
    # Дополняем выборку до минимально допустимой для building-basis (5 шт).
    for idx, (price, area) in enumerate([(90_500, 57), (89_000, 56.5), (90_000, 57.5)]):
        upsert_raw_listing(
            db_session,
            RawListing(
                source="test",
                source_id=f"extra-{idx}",
                url=f"https://test.local/extra-{idx}",
                title="Extra Паркент 2-комн",
                price=price,
                currency="USD",
                area_m2=area,
                rooms=2,
                district="Мирзо-Улугбекский район",
                address_raw="Паркентский, дом 18",
            ),
        )
    db_session.commit()

    building_key = normalize_building_key("Мирзо-Улугбекский район", "Паркентский, дом 18")
    estimate = estimate_market(
        db_session,
        district="Мирзо-Улугбекский район",
        rooms=2,
        area_m2=57.5,
        building_key=building_key,
        listing_price_per_m2=1198,
    )

    assert estimate.basis == "building"
    assert estimate.sample_size >= 5
    assert estimate.discount_percent is not None
    assert estimate.discount_percent >= 15
    assert estimate.is_below_market is True

