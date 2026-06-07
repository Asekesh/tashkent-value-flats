from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.models import ResidentialComplex
from app.scrapers.base import RawListing
from app.services.complex_stats import (
    build_comparison,
    complex_comparison_map,
    list_complex_stats,
)
from app.services.listings import upsert_raw_listing


def _raw(source_id, address, price, area=50.0, deal_type="sale"):
    return RawListing(
        source="uybor",
        source_id=source_id,
        url=f"https://t/{source_id}",
        title="2-комн",
        price=price,
        currency="USD",
        area_m2=area,
        rooms=2,
        district="Мирабадский район",
        address_raw=address,
        floor=4,
        total_floors=9,
        deal_type=deal_type,
    )


def _seed(db, name, ppms, deal_type="sale", area=50.0):
    # разный адрес (дом i) + цена → разные building_key/group_key, дедуп не схлопнет;
    # ЖК из текста = name у всех → один residential_complex_id.
    for i, ppm in enumerate(ppms):
        upsert_raw_listing(
            db, _raw(f"{name}-{deal_type}-{i}", f"ЖК {name}, дом {i}", ppm * area, area, deal_type)
        )
    db.commit()


def _rc_id(db, name):
    return db.scalar(select(ResidentialComplex.id).where(ResidentialComplex.name == name))


def test_list_complex_stats_threshold_and_median(db_session):
    s = get_settings()
    _seed(db_session, "Alpha", [1000, 1100, 1200, 1300, 1400])  # 5 → проходит порог
    _seed(db_session, "Beta", [900, 1500])  # 2 → ниже порога, не показываем
    stats = {st.name: st for st in list_complex_stats(db_session, s, deal_type="sale")}
    assert "Alpha" in stats and "Beta" not in stats
    a = stats["Alpha"]
    assert a.count == 5
    assert a.median_price_per_m2_usd == 1200.0
    assert a.median_price_usd == 60000.0
    assert a.min_price_usd == 50000.0


def test_comparison_map_and_build(db_session):
    s = get_settings()
    _seed(db_session, "Alpha", [1000, 1100, 1200, 1300, 1400])
    rc_id = _rc_id(db_session, "Alpha")
    cmap = complex_comparison_map(db_session, s, rc_ids=[rc_id], deal_type="sale")
    assert rc_id in cmap
    name, count, med = cmap[rc_id]
    assert count == 5 and med == 1200.0

    cheap = build_comparison(1000.0, name, count, med, below_threshold_percent=15.0)
    assert cheap.vs_complex_percent == round((1 - 1000 / 1200) * 100, 1)  # ~16.7
    assert cheap.is_below_complex is True  # 16.7 ≥ 15

    pricey = build_comparison(1400.0, name, count, med, below_threshold_percent=15.0)
    assert pricey.vs_complex_percent < 0 and pricey.is_below_complex is False


def test_thin_complex_excluded_from_comparison(db_session):
    s = get_settings()
    _seed(db_session, "Beta", [900, 1500])  # 2 листинга
    rc_id = _rc_id(db_session, "Beta")
    assert complex_comparison_map(db_session, s, rc_ids=[rc_id], deal_type="sale") == {}


def test_deal_type_scoped(db_session):
    s = get_settings()
    _seed(db_session, "Gamma", [8, 9, 10, 11, 12], deal_type="rent")
    rent = {st.name for st in list_complex_stats(db_session, s, deal_type="rent")}
    sale = {st.name for st in list_complex_stats(db_session, s, deal_type="sale")}
    assert "Gamma" in rent and "Gamma" not in sale


def test_api_complexes_and_listing_attaches_comparison(client, db_session):
    _seed(db_session, "Alpha", [1000, 1100, 1200, 1300, 1400])

    resp = client.get("/api/complexes", params={"deal_type": "sale"}).json()
    assert resp["total"] >= 1
    alpha = next(c for c in resp["items"] if c["name"] == "Alpha")
    assert alpha["count"] == 5 and alpha["median_price_per_m2_usd"] == 1200.0

    items = client.get("/api/listings", params={"deal_type": "sale"}).json()["items"]
    with_cm = [i for i in items if i.get("complex_market")]
    assert with_cm, "ожидали листинги со сравнением по ЖК"
    cm = with_cm[0]["complex_market"]
    assert cm["name"] == "Alpha" and cm["median_price_per_m2_usd"] == 1200.0
    assert "vs_complex_percent" in cm
