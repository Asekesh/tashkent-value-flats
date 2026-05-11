from app.services.scrape import run_scrape


def test_scrape_run_and_listing_filters(client, db_session):
    runs = run_scrape(db_session, source="all")
    assert {run.source for run in runs} == {"olx", "uybor", "realt24"}

    listings = client.get("/api/listings", params={"rooms": 2, "discount_min": 15})
    assert listings.status_code == 200
    payload = listings.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["market"]["is_below_market"] is True


def test_listing_detail_includes_market_estimate(client, db_session):
    run_scrape(db_session, source="all")
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

