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


def test_same_flat_reposted_with_price_drift_merges(db_session):
    # The same physical flat reposted by another seller with a different title
    # and a 1.6% higher ask. Hashed fingerprint won't match (address text and
    # price bucket diverge), so the loose floor-based fallback must catch it.
    first = RawListing(
        source="olx",
        source_id="4kJlt",
        url="https://olx.test/4kJlt",
        title="ЖК «Koh Ota» 2/2/9 Евроремонт обш: 72 кв.м ор: Лабзак, Себзор",
        price=1488000000,
        currency="UZS",
        area_m2=72,
        rooms=2,
        floor=2,
        total_floors=9,
        district="Шайхантахурский район",
        address_raw="ЖК «Koh Ota» Евроремонт ор: Лабзак, Себзор",
    )
    second = RawListing(
        source="olx",
        source_id="64477466",
        url="https://olx.test/64477466",
        title="Себзор Продаётса 2/2/9 Жк кох ота 72кв.м",
        price=1511220000,  # +1.6%
        currency="UZS",
        area_m2=72,
        rooms=2,
        floor=2,
        total_floors=9,
        district="Шайхантахурский район",
        address_raw="Себзор Продаётса Жк кох ота",
    )

    listing, _ = upsert_raw_listing(db_session, first)
    duplicate, is_new = upsert_raw_listing(db_session, second)
    db_session.commit()

    assert is_new is False
    assert duplicate.id == listing.id
    assert duplicate.duplicate_count == 2


def test_loose_dedup_merges_when_floor_missing_on_repost(db_session):
    # OLX repost with the floor field stripped. Same district/rooms/area and
    # price inside ±5% — under the relaxed scrape-time match, None floor is
    # treated as wildcard against the existing known floor.
    first = RawListing(
        source="olx",
        source_id="aaa",
        url="https://olx.test/aaa",
        title="2-комн с этажом",
        price=100000,
        currency="USD",
        area_m2=60,
        rooms=2,
        floor=5,
        total_floors=9,
        district="Мирабадский район",
        address_raw="ЖК Парус, 5/9",
    )
    second = RawListing(
        source="olx",
        source_id="bbb",
        url="https://olx.test/bbb",
        title="2-комн без этажа",
        price=101000,  # +1%
        currency="USD",
        area_m2=60,
        rooms=2,
        floor=None,
        total_floors=None,
        district="Мирабадский район",
        address_raw="Парус ЖК",
    )

    listing, _ = upsert_raw_listing(db_session, first)
    other, is_new = upsert_raw_listing(db_session, second)
    db_session.commit()

    assert is_new is False
    assert other.id == listing.id
    assert other.duplicate_count == 2


def test_loose_dedup_keeps_distinct_known_floors(db_session):
    # Same district/area/rooms/price-window but distinct known floors —
    # different physical flats, must not merge. Addresses differ so the hash
    # key path won't match either; the floor guard in find_duplicate_by_flat
    # is what keeps them apart.
    base = dict(
        source="olx",
        currency="USD",
        area_m2=60,
        rooms=2,
        district="Мирабадский район",
        total_floors=9,
    )
    first = RawListing(
        source_id="aaa",
        url="https://olx.test/aaa",
        title="2-комн 3/9",
        address_raw="дом на углу",
        price=100000,
        floor=3,
        **base,
    )
    second = RawListing(
        source_id="bbb",
        url="https://olx.test/bbb",
        title="2-комн 7/9",
        address_raw="совсем другой ориентир",
        price=101000,
        floor=7,
        **base,
    )

    listing, _ = upsert_raw_listing(db_session, first)
    other, is_new = upsert_raw_listing(db_session, second)
    db_session.commit()

    assert is_new is True
    assert other.id != listing.id


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

