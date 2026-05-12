from __future__ import annotations

from app.scrapers.base import RawListing
from app.services.listings import upsert_raw_listing
from app.services.market import estimate_market
from app.services.normalization import normalize_building_key
from app.services.segmentation import SEGMENT_NEW, SEGMENT_SECONDARY


def _raw(
    source_id: str,
    price: float,
    area: float,
    rooms: int = 2,
    *,
    floor: int | None = None,
    total_floors: int | None = None,
    description: str | None = None,
    title: str | None = None,
    address: str = "Building 1",
) -> RawListing:
    return RawListing(
        source="test",
        source_id=source_id,
        url=f"https://test.local/{source_id}",
        title=title or f"Flat {source_id}",
        price=price,
        currency="USD",
        area_m2=area,
        rooms=rooms,
        district="Test District",
        address_raw=address,
        floor=floor,
        total_floors=total_floors,
        description=description,
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


def test_discount_above_30_percent_is_hidden(db_session):
    # Здание с медианой $1200/м². Объявление по $700/м² — дисконт 41.7%,
    # выше нового кэпа -30%. В реальности это либо квартира другой категории
    # (хрущёвка/1й этаж), либо ошибка данных — скрываем.
    for i, area in enumerate([100, 95, 90, 85, 80]):
        upsert_raw_listing(db_session, _raw(f"d{i}", area * 1200, area))
    db_session.commit()

    building_key = normalize_building_key("Test District", "Building 1")

    estimate = estimate_market(
        db_session,
        district="Test District",
        rooms=2,
        area_m2=100,
        building_key=building_key,
        listing_price_per_m2=700,
    )
    assert estimate.market_price_per_m2_usd == 1200.0
    assert estimate.discount_percent is None
    assert estimate.is_below_market is False


def test_extreme_floor_listing_gets_no_discount(db_session):
    # Здоровая база $1200/м², объявление по $1000/м² — нормальный -16.7%
    # дисконт. Но если объявление на 1-м этаже — мы намеренно не считаем
    # ему дисконт (структурный дисконт этажа выглядел бы как «скидка»).
    for i, area in enumerate([100, 95, 90, 85, 80]):
        upsert_raw_listing(db_session, _raw(f"f{i}", area * 1200, area, floor=3, total_floors=9))
    db_session.commit()

    building_key = normalize_building_key("Test District", "Building 1")

    estimate = estimate_market(
        db_session,
        district="Test District",
        rooms=2,
        area_m2=100,
        building_key=building_key,
        listing_price_per_m2=1000,
        floor=1,
        total_floors=9,
    )
    assert estimate.market_price_per_m2_usd == 1200.0
    assert estimate.discount_percent is None
    assert estimate.is_below_market is False


def test_extreme_floors_excluded_from_base(db_session):
    # Пять объявлений по $1200/м² на средних этажах + три дешёвых ($700/м²)
    # на 1-м и последнем этажах. Если бы 1й/последний попали в базу,
    # медиана съехала бы ниже $1200. Должна остаться $1200.
    for i, area in enumerate([100, 95, 90, 85, 80]):
        upsert_raw_listing(db_session, _raw(f"m{i}", area * 1200, area, floor=4, total_floors=9))
    upsert_raw_listing(db_session, _raw("low1", 100 * 700, 100, floor=1, total_floors=9))
    upsert_raw_listing(db_session, _raw("low2", 95 * 700, 95, floor=9, total_floors=9))
    db_session.commit()

    building_key = normalize_building_key("Test District", "Building 1")

    estimate = estimate_market(
        db_session,
        district="Test District",
        rooms=2,
        area_m2=100,
        building_key=building_key,
        listing_price_per_m2=1000,
        floor=4,
        total_floors=9,
    )
    assert estimate.market_price_per_m2_usd == 1200.0


def test_newbuild_and_secondary_have_separate_bases(db_session):
    # Новостройки в этом «здании» по $1800/м², вторичка по $900/м².
    # Без сегментации медиана была бы где-то $1350, и обе группы выглядели
    # бы как «отклонение от рынка». С сегментацией каждая сравнивается
    # со своей категорией — оценка должна стать корректной.
    for i, area in enumerate([100, 95, 90, 85, 80]):
        upsert_raw_listing(
            db_session,
            _raw(f"nb{i}", area * 1800, area, floor=5, total_floors=12, description="Новостройка, евроремонт"),
        )
    for i, area in enumerate([100, 95, 90, 85, 80]):
        upsert_raw_listing(
            db_session,
            _raw(f"sc{i}", area * 900, area, floor=3, total_floors=4, description="Хрущёвка, средний ремонт"),
        )
    db_session.commit()

    building_key = normalize_building_key("Test District", "Building 1")

    new = estimate_market(
        db_session,
        district="Test District",
        rooms=2,
        area_m2=100,
        building_key=building_key,
        listing_price_per_m2=1700,
        segment=SEGMENT_NEW,
        floor=5,
        total_floors=12,
    )
    sec = estimate_market(
        db_session,
        district="Test District",
        rooms=2,
        area_m2=100,
        building_key=building_key,
        listing_price_per_m2=850,
        segment=SEGMENT_SECONDARY,
        floor=3,
        total_floors=4,
    )
    assert new.market_price_per_m2_usd == 1800.0
    assert sec.market_price_per_m2_usd == 900.0
