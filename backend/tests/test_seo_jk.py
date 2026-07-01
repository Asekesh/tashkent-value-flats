"""SEO ЖК-страницы: слаги, load_complex, роуты /jk, sitemap."""
from app.models import Listing, ResidentialComplex
from app.seo.slugs import complex_slug, complex_id_from_slug

CHILANZAR = "Чиланзарский район"


def _mk_complex(db, name, district=CHILANZAR):
    rc = ResidentialComplex(name=name, match_key=name.lower(), district=district)
    db.add(rc)
    db.flush()
    return rc


def _mk(db, i, rc_id, *, price_usd, area=50.0, rooms=2, district=CHILANZAR, status="active"):
    db.add(
        Listing(
            source="olx", source_id=f"j{i}", url=f"https://olx.uz/{i}",
            title=f"Кв {i}", price=price_usd, currency="USD", price_usd=price_usd,
            area_m2=area, price_per_m2_usd=price_usd / area, rooms=rooms,
            district=district, address_raw="ул. Т 1", duplicate_group_key=f"jg{i}",
            status=status, deal_type="sale", residential_complex_id=rc_id,
            is_below_market=True, discount_percent=10.0,
        )
    )


def _seed_complex(db, name="ЖК Нова", n=5, base_price=60000.0):
    rc = _mk_complex(db, name)
    for i in range(n):
        _mk(db, i, rc.id, price_usd=base_price + i * 1000, rooms=1 + (i % 3))
    db.commit()
    return rc


def test_complex_slug_roundtrip():
    assert complex_slug(42, "ЖК Нова Tashkent") == "42-zhk-nova-tashkent"
    assert complex_id_from_slug("42-zhk-nova-tashkent") == 42
    assert complex_id_from_slug("42") == 42
    assert complex_id_from_slug("42-любой-хвост") == 42
    assert complex_id_from_slug("nonsense") is None


def test_load_complex_medians(db_session):
    from app.core.config import get_settings
    from app.seo import service
    rc = _seed_complex(db_session, n=5, base_price=60000.0)  # 60k..64k, median 62k
    ch = service.load_complex(db_session, get_settings(), rc.id)
    assert ch is not None
    assert ch.name == "ЖК Нова"
    assert ch.total == 5
    assert ch.median_price_usd == 62000.0
    assert ch.min_price_usd == 60000.0
    assert len(ch.cards) == 5


def test_load_complex_missing_returns_none(db_session):
    from app.core.config import get_settings
    from app.seo import service
    assert service.load_complex(db_session, get_settings(), 999) is None


def test_jk_page_renders(client, db_session):
    rc = _seed_complex(db_session)
    r = client.get(f"/jk/{rc.id}-zhk-nova")
    assert r.status_code == 200
    assert "ЖК Нова" in r.text
    assert "Частые вопросы" in r.text
    assert "FAQPage" in r.text
    assert "ItemList" in r.text
    assert f'rel="canonical" href="https://uyradar.uz/jk/{rc.id}-zhk-nova"' in r.text


def test_jk_page_missing_404(client, db_session):
    _seed_complex(db_session)
    assert client.get("/jk/99999-nope").status_code == 404


def test_jk_catalog_lists_qualifying(client, db_session):
    rc_big = _seed_complex(db_session, name="ЖК Большой", n=5)
    # маленький ЖК (<5) — не в каталоге
    rc_small = _mk_complex(db_session, "ЖК Малый")
    _mk(db_session, 100, rc_small.id, price_usd=50000.0)
    db_session.commit()
    r = client.get("/jk")
    assert r.status_code == 200
    assert "ЖК Большой" in r.text
    assert "ЖК Малый" not in r.text


def test_sitemap_includes_jk(client, db_session):
    rc = _seed_complex(db_session)
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "https://uyradar.uz/jk</loc>" in r.text
    assert f"https://uyradar.uz/jk/{rc.id}-" in r.text
