from app.scrapers.registry import parse_fixture
from app.services.normalization import price_per_m2, to_usd


def test_olx_fixture_parser_normalizes_core_fields():
    listings = parse_fixture("olx")

    assert len(listings) == 3
    first = listings[0]
    assert first.source == "olx"
    assert first.rooms == 2
    assert first.area_m2 == 57.5
    assert first.currency == "UZS"
    assert first.district == "Мирзо-Улугбекский район"
    assert first.floor == 4
    assert first.total_floors == 9


def test_price_helpers_convert_to_usd_and_price_per_meter():
    price_usd = to_usd(1_270_000_000, "UZS")

    assert price_usd == 100000
    assert price_per_m2(price_usd, 50) == 2000

