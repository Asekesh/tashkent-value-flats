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


def _mk_rent(db, i, district, rooms, *, price_usd, status="active"):
    db.add(
        Listing(
            source="uybor", source_id=f"r{i}", url=f"https://uybor.uz/{i}",
            title=f"Аренда {i}", price=price_usd, currency="USD",
            price_usd=price_usd, area_m2=50.0, price_per_m2_usd=price_usd / 50.0,
            rooms=rooms, district=district, address_raw="ул. Тестовая 2",
            duplicate_group_key=f"rg{i}", status=status,
            deal_type="rent", price_period="month",
            is_below_market=True, discount_percent=15.0,
        )
    )


def _seed_rent(db):
    # Чиланзар аренда: 3 активных (2,2,3) по $300/$400/$600 в мес.
    for i, (rooms, price) in enumerate([(2, 300.0), (2, 400.0), (3, 600.0)]):
        _mk_rent(db, i, CHILANZAR, rooms, price_usd=price)
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


def test_load_hub_sale_unchanged(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed(db_session)
    data = service.load_hub(db_session, get_settings(), district=CHILANZAR)
    assert data.deal_type == "sale"
    assert data.total == 4
    assert data.avg_ppm_usd is not None


def test_load_hub_rent_uses_monthly_avg(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed_rent(db_session)
    data = service.load_hub(db_session, get_settings(), district=CHILANZAR, deal_type="rent")
    assert data.deal_type == "rent"
    assert data.price_period == "month"
    assert data.total == 3
    # средняя $/мес = (300+400+600)/3 = 433.3
    assert 430 <= data.avg_price_usd <= 437


def test_available_hubs_separates_deal_types(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed(db_session)
    _seed_rent(db_session)
    sale_d, _, _ = service.available_hubs(db_session, get_settings(), deal_type="sale")
    rent_d, _, _ = service.available_hubs(db_session, get_settings(), deal_type="rent")
    assert sale_d.get(CHILANZAR) == 4
    assert rent_d.get(CHILANZAR) == 3  # аренда считается отдельно


def test_cross_link_sale_to_rent(client, db_session):
    _seed(db_session)       # продажа Чиланзар
    _seed_rent(db_session)  # аренда Чиланзар
    r = client.get("/kvartira/chilanzar")
    assert r.status_code == 200
    assert 'href="/arenda/chilanzar"' in r.text
    assert "Снять" in r.text


def test_cross_link_absent_when_no_counterpart(client, db_session):
    _seed(db_session)       # только продажа
    r = client.get("/kvartira/chilanzar")
    assert r.status_code == 200
    assert 'href="/arenda/chilanzar"' not in r.text


def test_hub_v2_intro_and_faq_sale(client, db_session):
    _seed(db_session)
    r = client.get("/kvartira/chilanzar")
    assert r.status_code == 200
    assert "Цены по комнатности" in r.text   # таблица на district-only
    assert "FAQPage" in r.text                # FAQ JSON-LD
    assert "ItemList" in r.text               # список объявлений JSON-LD
    assert "Сколько стоит" in r.text          # видимый FAQ-вопрос


def test_hub_v2_rent_stats_and_table(client, db_session):
    _seed_rent(db_session)
    r = client.get("/arenda/chilanzar")
    assert r.status_code == 200
    assert "Цены по комнатности" in r.text
    assert "/мес" in r.text
    assert "FAQPage" in r.text


def test_hub_v2_combo_hides_rooms_table(client, db_session):
    _seed(db_session)
    r = client.get("/kvartira/chilanzar/2-komnatnye")
    assert r.status_code == 200
    assert "Цены по комнатности" not in r.text  # на комбо таблицы нет


def test_arenda_district_rooms_hub(client, db_session):
    _seed_rent(db_session)
    r = client.get("/arenda/chilanzar/2-komnatnye")
    assert r.status_code == 200
    assert "Аренда 2-комнатных квартир в Чиланзарском районе" in r.text
    assert "/мес" in r.text
    assert 'rel="canonical" href="https://uyradar.uz/arenda/chilanzar/2-komnatnye"' in r.text


def test_arenda_district_hub(client, db_session):
    _seed_rent(db_session)
    r = client.get("/arenda/chilanzar")
    assert r.status_code == 200
    assert "Аренда квартир в Чиланзарском районе" in r.text
    assert "/мес" in r.text


def test_arenda_empty_404(client, db_session):
    _seed(db_session)  # только продажа засеяна
    assert client.get("/arenda/chilanzar").status_code == 404


def test_rooms_breakdown_sale_avg_full_price(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed(db_session)  # Чиланзар: 3×2-комн ($50k), 1×3-комн ($50k)
    rows = service.rooms_breakdown(db_session, get_settings(), CHILANZAR, deal_type="sale")
    by_rooms = {r["rooms"]: r for r in rows}
    assert by_rooms[2]["count"] == 3
    assert by_rooms[3]["count"] == 1
    assert by_rooms[2]["avg_price"] == 50000.0


def test_rooms_breakdown_rent_avg_monthly(db_session):
    from app.core.config import get_settings
    from app.seo import service
    _seed_rent(db_session)  # 2×2-комн ($300,$400), 1×3-комн ($600)
    rows = service.rooms_breakdown(db_session, get_settings(), CHILANZAR, deal_type="rent")
    by_rooms = {r["rooms"]: r for r in rows}
    assert by_rooms[2]["count"] == 2
    assert by_rooms[2]["avg_price"] == 350.0
    assert by_rooms[3]["avg_price"] == 600.0


def test_sitemap_includes_rent(client, db_session):
    _seed(db_session)
    _seed_rent(db_session)
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "https://uyradar.uz/kvartira/chilanzar</loc>" in r.text
    assert "https://uyradar.uz/arenda/chilanzar</loc>" in r.text
    assert "https://uyradar.uz/arenda</loc>" in r.text


def test_arenda_catalog(client, db_session):
    _seed_rent(db_session)
    r = client.get("/arenda")
    assert r.status_code == 200
    assert "/arenda/chilanzar" in r.text
    assert "аренд" in r.text.lower()


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
