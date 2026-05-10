def test_scrape_run_and_listing_filters(client):
    response = client.post("/api/admin/scrape/run", json={"source": "all"})
    assert response.status_code == 200
    assert {run["source"] for run in response.json()} == {"olx", "uybor", "realt24"}

    listings = client.get("/api/listings", params={"rooms": 2, "discount_min": 15})
    assert listings.status_code == 200
    payload = listings.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["market"]["is_below_market"] is True


def test_listing_detail_includes_market_estimate(client):
    client.post("/api/admin/scrape/run", json={"source": "all"})
    listings = client.get("/api/listings", params={"rooms": 2}).json()["items"]
    listing_id = listings[0]["id"]

    detail = client.get(f"/api/listings/{listing_id}")

    assert detail.status_code == 200
    assert detail.json()["market"]["market_price_per_m2_usd"] is not None

