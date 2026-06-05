from app.services.market_estimate import recompute_all as recompute_market
from app.services.scrape import run_scrape


def test_scrape_run_and_listing_filters(client, db_session):
    runs = run_scrape(db_session, source="all")
    # «all» теперь включает rent-джобы (olx_rent/uybor_rent) — отдельные scrape-раны
    # по той же площадке, но с deal_type='rent'.
    assert {run.source for run in runs} == {"olx", "uybor", "realt24", "olx_rent", "uybor_rent"}
    # Полный пересчёт после скрейпа (в проде делается недельным rebuild loop'ом
    # либо разовой CLI; в тесте дёргаем вручную, чтобы поймать дрейф соседей).
    recompute_market(db_session)

    listings = client.get("/api/listings", params={"rooms": 2, "discount_min": 15})
    assert listings.status_code == 200
    payload = listings.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["market"]["is_below_market"] is True


def test_listing_detail_includes_market_estimate(client, db_session):
    run_scrape(db_session, source="all")
    recompute_market(db_session)
    listings = client.get("/api/listings", params={"rooms": 2}).json()["items"]
    listing_id = listings[0]["id"]

    detail = client.get(f"/api/listings/{listing_id}")

    assert detail.status_code == 200
    assert detail.json()["market"]["market_price_per_m2_usd"] is not None


def test_scrape_run_endpoint_starts_background(client):
    response = client.post("/api/admin/scrape/run", json={"source": "all", "mode": "auto"})
    assert response.status_code == 200
    body = response.json()
    assert "started" in body
    assert "progress" in body

