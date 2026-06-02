"""SEO-хабы: рендер лендингов по районам/комнатности и динамический sitemap."""
from app.models import Listing
from app.seo.slugs import district_from_slug, district_slug, rooms_from_slug

CHILANZAR = "Чиланзарский район"
YUNUSABAD = "Юнусабадский район"


def _mk(db, i, district, rooms, *, status="active", price_usd=50000.0, ppm=1000.0):
    db.add(
        Listing(
            source="olx",
            source_id=f"t{i}",
            url=f"https://olx.uz/{i}",
            title=f"Квартира {i}",
            price=price_usd,
            currency="USD",
            price_usd=price_usd,
            area_m2=50.0,
            price_per_m2_usd=ppm,
            rooms=rooms,
            district=district,
            address_raw="ул. Тестовая 1",
            duplicate_group_key=f"g{i}",
            status=status,
            is_below_market=True,
            discount_percent=20.0,
        )
    )


def _seed(db):
    # Чиланзар: 4 активных (2,2,2,3) + 1 снятое (не должно считаться).
    for i, rooms in enumerate([2, 2, 2, 3]):
        _mk(db, i, CHILANZAR, rooms)
    _mk(db, 99, CHILANZAR, 2, status="delisted")
    # Юнусабад: 3 активных, 3 комнаты.
    for i, rooms in enumerate([3, 3, 3], start=10):
        _mk(db, i, YUNUSABAD, rooms)
    db.commit()


def test_slug_roundtrip():
    assert district_slug(CHILANZAR) == "chilanzar"
    assert district_from_slug("chilanzar") == CHILANZAR
    assert district_from_slug("unknown") is None
    assert rooms_from_slug("2-komnatnye") == 2
    assert rooms_from_slug("chilanzar") is None


def test_catalog_lists_districts(client, db_session):
    _seed(db_session)
    r = client.get("/kvartira")
    assert r.status_code == 200
    assert "/kvartira/chilanzar" in r.text
    assert "Чиланзар" in r.text


def test_district_hub(client, db_session):
    _seed(db_session)
    r = client.get("/kvartira/chilanzar")
    assert r.status_code == 200
    # Снятое объявление не учитывается: 4 активных, не 5.
    assert "4 объявлени" in r.text
    assert "Квартиры в Чиланзарском районе" in r.text
    assert 'rel="canonical" href="https://uyradar.uz/kvartira/chilanzar"' in r.text
    assert 'name="description"' in r.text
    assert "BreadcrumbList" in r.text


def test_district_rooms_hub(client, db_session):
    _seed(db_session)
    r = client.get("/kvartira/chilanzar/2-komnatnye")
    assert r.status_code == 200
    assert "2-комнатные квартиры в Чиланзарском районе" in r.text
    assert "3 объявлени" in r.text


def test_rooms_only_hub(client, db_session):
    _seed(db_session)
    r = client.get("/kvartira/3-komnatnye")
    assert r.status_code == 200
    assert "3-комнатные квартиры в Ташкенте" in r.text


def test_unknown_slug_404(client, db_session):
    _seed(db_session)
    assert client.get("/kvartira/atlantida").status_code == 404


def test_empty_combo_404(client, db_session):
    _seed(db_session)
    # В Чиланзаре нет 9-комнатных.
    assert client.get("/kvartira/chilanzar/9-komnatnye").status_code == 404


def test_sitemap(client, db_session):
    _seed(db_session)
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert "<urlset" in r.text
    assert "https://uyradar.uz/kvartira/chilanzar</loc>" in r.text
    assert "https://uyradar.uz/kvartira/chilanzar/2-komnatnye</loc>" in r.text
    # Юнусабад есть (3 активных), а одиночного снятого Чиланзар-combo нет.
    assert "https://uyradar.uz/kvartira/yunusabad</loc>" in r.text
