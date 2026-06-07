from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Listing, ResidentialComplex
from app.scrapers.base import RawListing
from app.services.listings import (
    backfill_residential_complexes,
    remerge_residential_complexes,
    resolve_residential_complex,
    upsert_raw_listing,
)
from app.services.normalization import clean_complex_name, complex_match_key, extract_complex_name


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Новостройка / ЖК IMPERIAL Club City  Адрес : Яшнабад", "IMPERIAL Club City"),
        ("квартира в ЖК OzMakon, 1/5/16", "OzMakon"),
        ("жилой комплекс Паркент Плаза", "Паркент Плаза"),
        ("жилой комплекс Nest One", "Nest One"),
        ("ЖК «Mirabad Avenue» рядом метро", "Mirabad Avenue"),
        # Фигурные/«умные» кавычки (частый кейс OLX) — раньше глотали имя.
        ("Продаётся квартира в ЖК “Maftun Makon” 3 ком.", "Maftun Makon"),
        ("ж/к ‘Akay City’ срочно", "Akay City"),
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
    assert complex_match_key("Mirabad Avenue") == complex_match_key("MIRABAD  AVENUE")
    assert complex_match_key("Паркент Плаза") == complex_match_key("паркент   плаза")


@pytest.mark.parametrize(
    "a,b",
    [
        # листинговый шум / район / коды объявлений срезаются → один ключ
        ("Nest One", "Nest One вид"),
        ("Nest One", "Nest One Коробка"),
        ("Nest One", "Nest One Шайхантахурский"),
        ("Nest One", "Nest One ID"),
        ("Mirabad avenue", "Mirabad Avenue Мирабадский"),
        ("IMPERIAL Club City", "Imperial Club City Юнусабадский ID Срочно"),
        # EN↔RU фонетический канон заимствований
        ("Akay city", "Акай Сити"),
        ("Mirabad Avenue", "Мирабад Авеню"),
        ("Parkent Avenue", "Паркент Авеню"),
        ("Darhan Residence", "Дархан Резиденс"),
    ],
)
def test_match_key_merges_variants(a, b):
    assert complex_match_key(a) == complex_match_key(b)


@pytest.mark.parametrize(
    "a,b",
    [
        # бренд-слова РАЗНЫЕ → разные ЖК, склеивать нельзя
        ("Parkent Plaza", "Parkent Avenue"),
        ("Parkent Avenue", "Parkent Village"),
        ("NRG Oybek", "NRG U-Tower"),
        ("NRG Oybek", "NRG Mirzo Ulugbek"),
        ("Oz Mahal", "Oz Zamin"),
        ("Oz Zamin", "Oz Makon"),
        ("Assalom Sohil", "Assalom Havo"),
        ("Sayram Avenue", "Sayram Tower"),
        ("Nest One", "Nest Two"),
        ("Dream House", "Dream City"),
    ],
)
def test_match_key_keeps_distinct_complexes_apart(a, b):
    assert complex_match_key(a) != complex_match_key(b)


@pytest.mark.parametrize(
    "name",
    ["Новомосковская", "Паркентский", "Итальянский", "Яккасарайский"],
)
def test_district_word_as_complex_name_is_kept(name):
    # имя ЖК = район-подобное слово на «-ский/-ская»: режем район ТОЛЬКО при наличии
    # бренд-токена, иначе имя выродилось бы в пустой ключ и ЖК потерялся бы.
    assert len(complex_match_key(name)) >= 2
    assert clean_complex_name(name) == name
    assert extract_complex_name(f"ЖК {name} Город меняется") == name


def test_district_suffix_stripped_only_with_brand():
    # при наличии бренда «-ский»-хвост — шум и режется
    assert complex_match_key("Gardens Шайхантахурский") == complex_match_key("Gardens")
    assert complex_match_key("Mirabad Avenue Мирабадский") == complex_match_key("Mirabad avenue")


def test_extract_stops_at_noise_boundary():
    # шумовой токен — граница названия: не утаскиваем последующий бренд-токен
    assert extract_complex_name("ЖК Nest One вид на парк") == "Nest One"
    assert extract_complex_name("ЖК Mirabad Avenue Мирабадский ID Срочно") == "Mirabad Avenue"


def test_clean_complex_name_strips_noise():
    assert clean_complex_name("Nest One вид") == "Nest One"
    assert clean_complex_name("Mirabad Avenue Мирабадский ID") == "Mirabad Avenue"
    assert clean_complex_name("Срочно Квартира") == ""  # чистый шум → пусто


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


def _seed_complex(db_session, name, match_key, district=None):
    rc = ResidentialComplex(name=name, match_key=match_key, district=district)
    db_session.add(rc)
    db_session.flush()
    return rc


def test_remerge_consolidates_repoints_and_is_idempotent(db_session):
    # ДО-миграционное состояние: строки-варианты одного ЖК с РАЗНЫМИ старыми
    # ключами (nestone/nestonevid — один ЖК; akaycity/akaysiti — другой, EN+RU).
    variants = [
        ("Nest One", "nestone"),
        ("Nest One вид", "nestonevid"),
        ("Akay city", "akaycity"),
        ("Акай Сити", "akaysiti"),
    ]
    rcs = [_seed_complex(db_session, n, k) for n, k in variants]
    for i, rc in enumerate(rcs):
        # разные цена/площадь → не схлопнутся дедупом листингов
        l, _ = upsert_raw_listing(
            db_session, _raw(source_id=f"R{i}", address="ул. Тест", price=60000 + i * 7000, area_m2=55 + i * 4)
        )
        l.residential_complex_id = rc.id
    db_session.commit()

    dry = remerge_residential_complexes(db_session, dry_run=True)
    assert dry["rows_deleted"] == 2 and dry["merge_groups"] == 2 and dry["complexes_after"] == 2
    assert db_session.scalar(select(func.count()).select_from(ResidentialComplex)) == 4  # dry не пишет

    res = remerge_residential_complexes(db_session)
    assert res["rows_deleted"] == 2
    assert res["listings_repointed"] == 2
    assert res["complexes_after"] == 2
    assert db_session.scalar(select(func.count()).select_from(ResidentialComplex)) == 2

    # два ЖК осталось: nestone и akaycity; все 4 листинга разложены 2+2
    keys = set(db_session.scalars(select(ResidentialComplex.match_key)).all())
    assert keys == {"nestone", "akaycity"}
    by_complex = dict(
        db_session.execute(
            select(Listing.residential_complex_id, func.count()).group_by(Listing.residential_complex_id)
        ).all()
    )
    assert sorted(by_complex.values()) == [2, 2]

    # идемпотентность: повторный прогон ничего не трогает
    again = remerge_residential_complexes(db_session)
    assert again["rows_deleted"] == 0 and again["merge_groups"] == 0 and again["complexes_after"] == 2


def test_remerge_drops_noise_orphans(db_session):
    # строка, чьё имя выродилось в чистый шум (нового валидного ключа нет) →
    # листинг отвязывается, строка удаляется.
    rc = _seed_complex(db_session, "Срочно Квартира", "srochnokvartira")
    listing, _ = upsert_raw_listing(db_session, _raw(source_id="ORPH", address="ул. Тест"))
    listing.residential_complex_id = rc.id
    db_session.commit()

    res = remerge_residential_complexes(db_session)
    assert res["orphans_dropped"] == 1
    db_session.refresh(listing)
    assert listing.residential_complex_id is None
    assert db_session.scalar(select(func.count()).select_from(ResidentialComplex)) == 0


def test_backfill_cursor_pagination_skips_non_complex(db_session):
    # Два объявления с ЖК + одно без. Курсорная пагинация (after_id) НЕ должна
    # зацикливаться на «без ЖК» (оно остаётся с NULL-FK).
    specs = [("ЖК Alpha", 60000, 55), ("ул. Пушкина 5", 70000, 70), ("ЖК Gamma", 80000, 85)]
    for i, (addr, price, area) in enumerate(specs):
        l, _ = upsert_raw_listing(db_session, _raw(source_id=f"P{i}", address=addr, price=price, area_m2=area))
        l.residential_complex_id = None
    db_session.commit()

    cursor, total_scanned, total_updated, rounds = 0, 0, 0, 0
    while True:
        rounds += 1
        assert rounds < 10  # защита от зацикливания
        r = backfill_residential_complexes(db_session, limit=1, after_id=cursor)
        total_scanned += r["scanned"]
        total_updated += r["updated"]
        if r["scanned"] == 0:
            break
        cursor = r["next_after_id"]

    assert total_scanned == 3  # каждая строка просмотрена ровно раз
    assert total_updated == 2  # FK проставлен только двум с ЖК
    assert db_session.scalar(select(func.count()).select_from(ResidentialComplex)) == 2
