from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.models import Listing
from app.scrapers.base import RawListing
from app.services.listings import upsert_raw_listing
from app.services.rental_yield import yield_for_sale_listing, yields_for_rows


def _raw(source_id, name, ppm, *, area=50.0, deal_type="sale", rooms=2, district="Мирабадский район"):
    return RawListing(
        source="uybor",
        source_id=source_id,
        url=f"https://t/{source_id}",
        title=f"{rooms}-комн",
        price=ppm * area,
        currency="USD",
        area_m2=area,
        rooms=rooms,
        district=district,
        address_raw=f"ЖК {name}, дом {source_id}",
        floor=4,
        total_floors=9,
        deal_type=deal_type,
    )


def _seed(db, name, ppms, *, deal_type="sale", area=50.0, rooms=2, district="Мирабадский район"):
    for i, ppm in enumerate(ppms):
        upsert_raw_listing(
            db,
            _raw(f"{name}-{deal_type}-{i}", name, ppm, area=area, deal_type=deal_type, rooms=rooms, district=district),
        )
    db.commit()


def _sale(db, source_id):
    return db.scalars(select(Listing).where(Listing.source_id == source_id)).first()


def test_yield_by_complex(db_session):
    s = get_settings()
    _seed(db_session, "Alpha", [1000, 1100, 1200, 1300, 1400])  # sale, median ppm 1200
    _seed(db_session, "Alpha", [9, 10, 11, 12, 13], deal_type="rent")  # rent, median 11/m2/mo

    listing = _sale(db_session, "Alpha-sale-0")  # ppm 1000
    ry = yield_for_sale_listing(db_session, s, listing)
    assert ry is not None and ry.basis == "complex"
    # 11*12/1000*100 = 13.2%
    assert ry.gross_yield_percent == 13.2
    assert ry.payback_years == round(100 / 13.2, 1)
    assert ry.sample_size == 5


def test_district_fallback_when_no_rent_in_complex(db_session):
    s = get_settings()
    _seed(db_session, "Solo", [1000, 1100, 1200, 1300, 1400])  # sale only, нет аренды в этом ЖК
    # аренда в ТОМ ЖЕ районе/комнатности, но в другом ЖК → ступень «район+комнаты»
    _seed(db_session, "RentHub", [9, 10, 11, 12, 13], deal_type="rent")

    listing = _sale(db_session, "Solo-sale-2")  # ppm 1200
    ry = yield_for_sale_listing(db_session, s, listing)
    assert ry is not None and ry.basis == "district"
    # 11*12/1200*100 = 11.0%
    assert ry.gross_yield_percent == 11.0


def test_no_yield_without_rent(db_session):
    s = get_settings()
    _seed(db_session, "DryDistrict", [1000, 1100, 1200, 1300, 1400], district="Юнусабадский район")
    listing = _sale(db_session, "DryDistrict-sale-0")
    assert yield_for_sale_listing(db_session, s, listing) is None


def test_sanity_clips_absurd_yield(db_session):
    s = get_settings()
    # дешёвая продажа + дорогая аренда → доходность >20%, рассогласованные данные → прячем
    _seed(db_session, "Cheap", [150, 160, 170, 180, 190])
    _seed(db_session, "Cheap", [12, 13, 14, 15, 16], deal_type="rent")  # median 14
    listing = _sale(db_session, "Cheap-sale-0")  # ppm 150 → 14*12/150 = 112%
    assert yield_for_sale_listing(db_session, s, listing) is None


def test_rent_feed_gets_no_yield(db_session):
    s = get_settings()
    _seed(db_session, "Alpha", [9, 10, 11, 12, 13], deal_type="rent")
    rows = db_session.scalars(select(Listing).where(Listing.deal_type == "rent")).all()
    assert yields_for_rows(db_session, s, rows, "rent") == {}


def test_api_listing_attaches_yield(client, db_session):
    _seed(db_session, "Alpha", [1000, 1100, 1200, 1300, 1400])
    _seed(db_session, "Alpha", [9, 10, 11, 12, 13], deal_type="rent")

    items = client.get("/api/listings", params={"deal_type": "sale"}).json()["items"]
    with_y = [i for i in items if i.get("rental_yield")]
    assert with_y, "ожидали sale-листинги с доходностью"
    y = with_y[0]["rental_yield"]
    assert 1.0 <= y["gross_yield_percent"] <= 20.0
    assert y["payback_years"] > 0 and y["basis"] in ("complex", "district")

    # на вкладке аренды доходности нет
    rent_items = client.get("/api/listings", params={"deal_type": "rent"}).json()["items"]
    assert all(i.get("rental_yield") is None for i in rent_items)
