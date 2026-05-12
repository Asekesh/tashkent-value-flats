from app.scrapers.base import RawListing
from app.services.listings import upsert_raw_listing
from app.services.market import estimate_market
from app.services.normalization import normalize_building_key


def _raw(source_id: str, price: float, area: float, rooms: int = 2) -> RawListing:
    return RawListing(
        source="test",
        source_id=source_id,
        url=f"https://test.local/{source_id}",
        title=f"Flat {source_id}",
        price=price,
        currency="USD",
        area_m2=area,
        rooms=rooms,
        district="Test District",
        address_raw="Building 1",
    )


def test_building_median_and_savings(db_session):
    # Пять объявлений (building, 2-комн) с медианой $1200/м². Один выброс
    # снизу не должен сдвигать рынок — медиана его игнорирует.
    samples = [
        _raw("b1", 120_000, 100),  # 1200
        _raw("b2", 96_000, 80),    # 1200
        _raw("b3", 110_000, 90),   # ~1222
        _raw("b4", 90_000, 75),    # 1200
        _raw("b5", 50_000, 100),   # 500 — выброс снизу
    ]
    for raw in samples:
        upsert_raw_listing(db_session, raw)
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

    assert estimate.basis == "building"
    assert estimate.sample_size == 5
    # Медиана 500, 1200, 1200, 1200, 1222 = 1200
    assert estimate.market_price_per_m2_usd == 1200.0
    assert estimate.discount_percent == 25.0
    assert estimate.savings_usd == 36000.0
    assert estimate.is_below_market is True


def test_extreme_discount_is_hidden(db_session):
    # 5 уникальных объявлений (разная площадь, чтобы не схлопнулись дедупом),
    # все ~$1200/м² — нормальный рынок здания.
    for i, area in enumerate([100, 95, 90, 85, 80]):
        upsert_raw_listing(db_session, _raw(f"x{i}", area * 1200, area))
    db_session.commit()

    building_key = normalize_building_key("Test District", "Building 1")

    # Объявление с фейковой ценой $30/м² — дисконт получился бы 97%+, прячем.
    estimate = estimate_market(
        db_session,
        district="Test District",
        rooms=2,
        area_m2=100,
        building_key=building_key,
        listing_price_per_m2=30,
    )
    assert estimate.market_price_per_m2_usd == 1200.0
    assert estimate.discount_percent is None
    assert estimate.is_below_market is False


def test_outlier_listing_excluded_from_index(db_session):
    # Одно объявление с дикой ценой $40 000/м² не должно попасть в выборку
    # для медианы — иначе средняя по зданию улетит в космос.
    for i, area in enumerate([100, 95, 90, 85]):
        upsert_raw_listing(db_session, _raw(f"n{i}", area * 1200, area))  # ~$1200/м²
    # Фейк: 100м² за $4M = $40 000/м² — выпадает за пределы [400, 3000]/м²
    # и не попадает в индекс вовсе.
    upsert_raw_listing(db_session, _raw("fake", 4_000_000, 105))
    db_session.commit()

    building_key = normalize_building_key("Test District", "Building 1")

    estimate = estimate_market(
        db_session,
        district="Test District",
        rooms=2,
        area_m2=100,
        building_key=building_key,
        listing_price_per_m2=1000,
    )
    # Только 4 «здоровых» объявления — недостаточно для building-basis (min 5).
    # Падаем на district_rooms, который тоже отбрасывает выброс.
    assert estimate.market_price_per_m2_usd == 1200.0
    assert estimate.basis in {"building", "district_rooms"}
