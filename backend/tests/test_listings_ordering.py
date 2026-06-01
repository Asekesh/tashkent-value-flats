"""Регрессия на перенос сортировки/пагинации в БД (api/listings.get_listings).

Проверяем, что БД-сортировка отдаёт корректный порядок для всех режимов,
что пагинация — согласованный срез полного порядка, и что total при
discount_min считается по тем же правилам, что и раньше.
"""
from app.services.market_estimate import recompute_all as recompute_market
from app.services.scrape import run_scrape


def _seed(db_session):
    run_scrape(db_session, source="all")
    recompute_market(db_session)


def _ids(payload):
    return [item["id"] for item in payload["items"]]


def _discount(item):
    market = item.get("market")
    return market["discount_percent"] if market else None


def test_discount_sort_is_non_increasing_nulls_last(client, db_session):
    _seed(db_session)
    items = client.get("/api/listings", params={"sort": "discount", "limit": 200}).json()["items"]

    discounts = [_discount(i) for i in items]
    present = [d for d in discounts if d is not None]
    # Непустые дисконты идут по убыванию...
    assert present == sorted(present, reverse=True)
    # ...и все они раньше любого None (NULLS LAST == старый сентинель -999).
    first_none = next((idx for idx, d in enumerate(discounts) if d is None), len(discounts))
    assert all(d is not None for d in discounts[:first_none])
    assert all(d is None for d in discounts[first_none:])


def test_price_and_ppm_sorts_are_non_decreasing(client, db_session):
    _seed(db_session)

    by_price = client.get("/api/listings", params={"sort": "price", "limit": 200}).json()["items"]
    prices = [i["price_usd"] for i in by_price]
    assert prices == sorted(prices)

    by_ppm = client.get("/api/listings", params={"sort": "price_per_m2", "limit": 200}).json()["items"]
    ppms = [i["price_per_m2_usd"] for i in by_ppm]
    assert ppms == sorted(ppms)


def test_fresh_sort_is_newest_first(client, db_session):
    _seed(db_session)
    items = client.get("/api/listings", params={"sort": "fresh", "limit": 200}).json()["items"]
    seen = [i["seen_at"] for i in items]
    assert seen == sorted(seen, reverse=True)


def test_pagination_is_consistent_slice_of_full_order(client, db_session):
    _seed(db_session)
    full = _ids(client.get("/api/listings", params={"sort": "discount", "limit": 200}).json())

    # Постранично по 3 — конкатенация должна совпасть с полным порядком.
    paged: list[int] = []
    offset = 0
    while True:
        page = client.get(
            "/api/listings", params={"sort": "discount", "limit": 3, "offset": offset}
        ).json()
        ids = _ids(page)
        if not ids:
            break
        paged.extend(ids)
        offset += 3
        if offset > page["total"]:
            break

    assert paged == full
    # total стабилен и равен длине полного списка.
    assert len(full) == client.get("/api/listings", params={"limit": 200}).json()["total"]


def test_discount_min_filters_and_counts_correctly(client, db_session):
    _seed(db_session)
    payload = client.get(
        "/api/listings", params={"discount_min": 10, "limit": 200}
    ).json()

    # Каждый возвращённый листинг реально проходит порог...
    for item in payload["items"]:
        assert _discount(item) is not None
        assert _discount(item) >= 10
    # ...и total == числу таких листингов (страница вмещает всех при limit=200).
    assert payload["total"] == len(payload["items"])
