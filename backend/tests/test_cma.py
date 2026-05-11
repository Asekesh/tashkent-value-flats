from app.scrapers.base import RawListing
from app.services.cma import build_cma
from app.services.listings import upsert_raw_listing


def _seed(db, source_id, area, price, address="Building 1", district="Test District"):
    raw = RawListing(
        source="test",
        source_id=source_id,
        url=f"https://test.local/{source_id}",
        title=f"Flat {source_id}",
        price=price,
        currency="USD",
        area_m2=area,
        rooms=2,
        district=district,
        address_raw=address,
    )
    listing, _ = upsert_raw_listing(db, raw)
    return listing


def test_cma_uses_building_when_available(db_session):
    subject = _seed(db_session, "a1", area=100, price=105_000)
    _seed(db_session, "a2", area=95, price=120_000)
    _seed(db_session, "a3", area=105, price=126_000)
    db_session.commit()

    result = build_cma(db_session, subject)

    assert result.basis == "building"
    assert result.stats.count == 2
    assert result.stats.median_price_per_m2_usd is not None
    assert all(a.id != subject.id for a in result.analogs)


def test_cma_filters_area_within_15_percent(db_session):
    subject = _seed(db_session, "s1", area=100, price=100_000)
    # within ±15%
    _seed(db_session, "ok1", area=90, price=108_000)
    # outside ±15%
    _seed(db_session, "skip1", area=70, price=84_000)
    _seed(db_session, "skip2", area=130, price=156_000)
    db_session.commit()

    result = build_cma(db_session, subject)
    ids = {a.id for a in result.analogs}
    assert len(ids) == 1


def test_cma_falls_back_to_district(db_session):
    subject = _seed(db_session, "x1", area=100, price=100_000, address="Building A")
    _seed(db_session, "x2", area=95, price=114_000, address="Building B")
    _seed(db_session, "x3", area=105, price=126_000, address="Building C")
    db_session.commit()

    result = build_cma(db_session, subject)

    assert result.basis == "district"
    assert result.stats.count == 2
