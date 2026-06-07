from app.scrapers.base import RawListing
from app.services.cma import build_cma
from app.services.listings import upsert_raw_listing


def _seed(
    db,
    source_id,
    area,
    price,
    address="Building 1",
    district="Test District",
    title=None,
    description=None,
    floor=None,
    total_floors=None,
):
    raw = RawListing(
        source="test",
        source_id=source_id,
        url=f"https://test.local/{source_id}",
        title=title if title is not None else f"Flat {source_id}",
        price=price,
        currency="USD",
        area_m2=area,
        rooms=2,
        district=district,
        address_raw=address,
        floor=floor,
        total_floors=total_floors,
        description=description,
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


def test_cma_prefers_complex_when_enough_analogs(db_session):
    # ≥ MIN_COMPLEX_ANALOGS строгих аналогов в одном ЖК → базис «complex» (выше дома).
    # Разные площади/«дом N» → flat-дедуп не схлопнет; общий ЖК через текст адреса.
    subject = _seed(db_session, "c1", area=50, price=60_000, address="ЖК Alpha, дом 1", floor=4)
    _seed(db_session, "c2", area=52, price=64_000, address="ЖК Alpha, дом 2", floor=5)
    _seed(db_session, "c3", area=54, price=70_000, address="ЖК Alpha, дом 3", floor=4)
    _seed(db_session, "c4", area=56, price=78_000, address="ЖК Alpha, дом 4", floor=5)
    _seed(db_session, "d1", area=51, price=90_000, address="ЖК Beta, дом 1", floor=4)  # другой ЖК
    db_session.commit()

    result = build_cma(db_session, subject)
    assert result.basis == "complex"
    assert result.stats.count == 3  # c2,c3,c4 (subject исключён, Beta не входит)
    assert all(a.id != subject.id for a in result.analogs)


def test_cma_thin_complex_falls_through(db_session):
    # < MIN_COMPLEX_ANALOGS в ЖК → не «complex», падаем на дом/район
    subject = _seed(db_session, "t1", area=50, price=60_000, address="ЖК Gamma, дом 1", floor=4)
    _seed(db_session, "t2", area=52, price=64_000, address="ЖК Gamma, дом 2", floor=5)
    db_session.commit()

    result = build_cma(db_session, subject)
    assert result.basis != "complex"


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


def test_cma_prefers_micro_location_over_district(db_session):
    """Феруза-vs-Ц-1 кейс: один и тот же район, но разные массивы → не аналоги."""
    subject = _seed(
        db_session,
        "m1",
        area=100,
        price=100_000,
        address="массив Феруза 5",
        title="2-комн в массиве Феруза",
    )
    # тот же массив → должен попасть как аналог через micro_location
    _seed(
        db_session,
        "m2",
        area=95,
        price=95_000,
        address="массив Феруза 12",
        title="2-комн в массиве Феруза",
    )
    # другой массив (Ц-1) того же района → не должен попасть в строгий пул
    _seed(
        db_session,
        "m3",
        area=100,
        price=180_000,
        address="Ц-1, дом 8",
        title="2-комн Ц-1",
    )
    db_session.commit()

    result = build_cma(db_session, subject)
    assert result.basis == "micro_location"
    ids = {a.id for a in result.analogs}
    assert len(ids) == 1
    # средний дорогой кандидат из Ц-1 не подтянулся → медиана близка к 1000 $/м²,
    # а не к 1800.
    assert result.stats.median_price_per_m2_usd is not None
    assert result.stats.median_price_per_m2_usd < 1200


def test_cma_excludes_different_material(db_session):
    subject = _seed(
        db_session,
        "mat1",
        area=100,
        price=100_000,
        address="Чехова 5",
        title="2-комн панельная",
    )
    # тот же дом, тоже панель → аналог
    _seed(
        db_session,
        "mat2",
        area=95,
        price=95_000,
        address="Чехова 5",
        title="2-комн панельная квартира",
    )
    # тот же дом, но кирпич → отсекаем по материалу
    _seed(
        db_session,
        "mat3",
        area=100,
        price=140_000,
        address="Чехова 5",
        title="2-комн кирпичная квартира",
    )
    db_session.commit()

    result = build_cma(db_session, subject)
    assert result.basis == "building"
    assert result.stats.count == 1


def test_cma_excludes_distant_floor(db_session):
    subject = _seed(
        db_session,
        "f1",
        area=100,
        price=100_000,
        address="Чехова 5",
        floor=5,
        total_floors=9,
    )
    # этаж 6 (±1) → аналог
    _seed(
        db_session,
        "f2",
        area=95,
        price=95_000,
        address="Чехова 5",
        floor=6,
        total_floors=9,
    )
    # этаж 8 (±3) → отсекаем по этажу
    _seed(
        db_session,
        "f3",
        area=100,
        price=110_000,
        address="Чехова 5",
        floor=8,
        total_floors=9,
    )
    db_session.commit()

    result = build_cma(db_session, subject)
    assert result.basis == "building"
    assert result.stats.count == 1


def test_cma_excludes_extreme_floor_for_middle_subject(db_session):
    subject = _seed(
        db_session,
        "ef1",
        area=100,
        price=100_000,
        address="Чехова 5",
        floor=4,
        total_floors=9,
    )
    # 5 этаж — средний, ОК
    _seed(
        db_session,
        "ef2",
        area=100,
        price=105_000,
        address="Чехова 5",
        floor=5,
        total_floors=9,
    )
    # 1 этаж — крайний, не сравниваем со средним subject
    _seed(
        db_session,
        "ef3",
        area=100,
        price=70_000,
        address="Чехова 5",
        floor=1,
        total_floors=9,
    )
    db_session.commit()

    result = build_cma(db_session, subject)
    assert result.basis == "building"
    assert result.stats.count == 1


def test_cma_excludes_different_era_by_year(db_session):
    # Distinct floors per listing so the relaxed loose-dedup (which would
    # otherwise merge same-address rows within ±5% price) keeps them apart.
    subject = _seed(
        db_session,
        "y1",
        area=100,
        price=100_000,
        address="Чехова 5",
        description="2-комн, год постройки 2022, евроремонт",
        floor=3,
    )
    # та же эпоха (2025) → ОК
    _seed(
        db_session,
        "y2",
        area=100,
        price=105_000,
        address="Чехова 5",
        description="2-комн, год постройки 2025",
        floor=4,
    )
    # старый фонд (1980) → отсекаем
    _seed(
        db_session,
        "y3",
        area=100,
        price=60_000,
        address="Чехова 5",
        description="2-комн, год постройки 1980, старый фонд",
        floor=5,
    )
    db_session.commit()

    result = build_cma(db_session, subject)
    assert result.basis == "building"
    assert result.stats.count == 1


def test_cma_excludes_different_segment(db_session):
    # Distinct floors so the relaxed loose-dedup doesn't merge same-address
    # rows with prices inside its ±5% window.
    subject = _seed(
        db_session,
        "s_new",
        area=100,
        price=100_000,
        address="Чехова 5",
        title="2-комн новостройка",
        floor=3,
    )
    # новостройка → ОК
    _seed(
        db_session,
        "s_new2",
        area=100,
        price=105_000,
        address="Чехова 5",
        title="2-комн новостройка сдан",
        floor=4,
    )
    # вторичка → отсекаем
    _seed(
        db_session,
        "s_old",
        area=100,
        price=60_000,
        address="Чехова 5",
        title="2-комн хрущёвка",
        floor=5,
    )
    db_session.commit()

    result = build_cma(db_session, subject)
    assert result.basis == "building"
    assert result.stats.count == 1


def test_cma_relaxes_to_district_when_strict_pool_empty(db_session):
    """Если строгие фильтры всё выбили — возвращаемся к району с пометкой."""
    subject = _seed(
        db_session,
        "r1",
        area=100,
        price=100_000,
        address="Building A",
        title="2-комн панельная",
    )
    # тот же район, но материал другой → не пройдёт строгий, но district_relaxed подтянет
    _seed(
        db_session,
        "r2",
        area=100,
        price=140_000,
        address="Building B",
        title="2-комн кирпичная",
    )
    db_session.commit()

    result = build_cma(db_session, subject)
    assert result.basis == "district_relaxed"
    assert result.stats.count == 1
