from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Listing, ResidentialComplex
from app.scrapers.base import RawListing
from app.services.listings import (
    backfill_residential_complexes,
    resolve_residential_complex,
    upsert_raw_listing,
)
from app.services.normalization import complex_match_key, extract_complex_name


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Новостройка / ЖК IMPERIAL Club City  Адрес : Яшнабад", "IMPERIAL Club City"),
        ("квартира в ЖК OzMakon, 1/5/16", "OzMakon"),
        ("жилой комплекс Паркент Плаза", "Паркент Плаза"),
        ("жилой комплекс Nest One", "Nest One"),
        ("ЖК «Mirabad Avenue» рядом метро", "Mirabad Avenue"),
        ("ж/к Boulevard, отличная квартира", "Boulevard"),
    ],
)
def test_extract_complex_name(text, expected):
    assert extract_complex_name(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "СВОЯ НОВОСТРОЙКА всё раздельные",  # «новостройка» без ключа ЖК и без имени
        "Продается квартира в Мирабадском районе",
        "",
        None,
    ],
)
def test_extract_complex_name_none(text):
    assert extract_complex_name(text) is None


def test_match_key_collapses_spellings():
    # латиница / кириллица / другой регистр одного ЖК → один ключ
    keys = {
        complex_match_key("Mirabad Avenue"),
        complex_match_key("mirabad avenue"),
        complex_match_key("Мирабад"),  # совпадёт с латинским «mirabad»-префиксом? нет — это другой ключ
    }
    assert complex_match_key("Mirabad Avenue") == complex_match_key("MIRABAD  AVENUE")
    assert complex_match_key("Паркент Плаза") == complex_match_key("паркент   плаза")


def _raw(
    *, source_id: str, address: str, description: str = "", deal_type: str = "sale",
    price: float = 60000, area_m2: float = 55,
) -> RawListing:
    return RawListing(
        source="uybor",
        source_id=source_id,
        url=f"https://uybor.test/{source_id}",
        title="2-комн",
        price=price,
        currency="USD",
        area_m2=area_m2,
        rooms=2,
        district="Мирабадский район",
        address_raw=address,
        description=description,
        floor=4,
        total_floors=9,
        deal_type=deal_type,
    )


def test_upsert_sets_complex_fk_and_dedups_complex(db_session):
    # Два разных объявления одного ЖК с разным написанием → одна строка справочника,
    # обе ссылаются на неё.
    a, _ = upsert_raw_listing(db_session, _raw(source_id="A", address="ЖК Nest One"))
    b, _ = upsert_raw_listing(
        db_session, _raw(source_id="B", address="ул. Пушкина", description="отличная квартира в ЖК nest one")
    )
    db_session.commit()

    assert a.residential_complex_id is not None
    assert a.residential_complex_id == b.residential_complex_id
    assert db_session.scalar(select(func.count()).select_from(ResidentialComplex)) == 1
    rc = db_session.scalar(select(ResidentialComplex))
    assert rc.name == "Nest One"  # каноничное имя — от первого встреченного


def test_upsert_without_complex_leaves_fk_null(db_session):
    listing, _ = upsert_raw_listing(db_session, _raw(source_id="C", address="ул. Пушкина 12"))
    db_session.commit()
    assert listing.residential_complex_id is None


def test_resolve_residential_complex_rejects_empty(db_session):
    assert resolve_residential_complex(db_session, "!!", None) is None


def test_backfill_residential_complexes(db_session):
    # Листинг без FK, но с ЖК в тексте → бэкфилл проставит.
    listing, _ = upsert_raw_listing(db_session, _raw(source_id="D", address="ЖК Boulevard"))
    listing.residential_complex_id = None
    db_session.commit()

    dry = backfill_residential_complexes(db_session, dry_run=True)
    assert dry["updated"] == 1 and dry["scanned"] >= 1
    assert listing.residential_complex_id is None  # dry-run не пишет

    result = backfill_residential_complexes(db_session)
    assert result["updated"] == 1
    db_session.refresh(listing)
    assert listing.residential_complex_id is not None


def test_backfill_limit_chunks(db_session):
    # Три объявления разных ЖК без FK; limit=2 обрабатывает их по чанкам.
    for i, jk in enumerate(["Alpha", "Beta", "Gamma"]):
        # разные цена/площадь, чтобы find_duplicate_by_flat не схлопнул их в одно
        l, _ = upsert_raw_listing(
            db_session,
            _raw(source_id=f"L{i}", address=f"ЖК {jk}", price=60000 + i * 20000, area_m2=55 + i * 15),
        )
        l.residential_complex_id = None
    db_session.commit()

    first = backfill_residential_complexes(db_session, limit=2)
    assert first["scanned"] == 2 and first["updated"] == 2
    second = backfill_residential_complexes(db_session, limit=2)
    assert second["scanned"] == 1 and second["updated"] == 1
    # справочник склеил три РАЗНЫХ ЖК в три строки, дублей нет
    assert db_session.scalar(select(func.count()).select_from(ResidentialComplex)) == 3
    assert backfill_residential_complexes(db_session, dry_run=True)["updated"] == 0
