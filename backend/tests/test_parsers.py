from app.scrapers.registry import parse_fixture
from app.scrapers.adapters.olx import OlxAdapter
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


def test_olx_live_jsonld_parser_extracts_listing_fields():
    html = """
    <html><body>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "offers": {
          "@type": "AggregateOffer",
          "offers": [
            {
              "@type": "Offer",
              "priceCurrency": "UZS",
              "areaServed": {"@type": "AdministrativeArea", "name": "Яккасарайский район"},
              "name": "Яккасарай 2/6/6 65м2 евро люкс",
              "price": 1028312999,
              "url": "https://www.olx.uz/d/obyavlenie/test-ID4mkIT.html",
              "image": ["https://example.test/image.jpg"]
            }
          ]
        }
      }
      </script>
    </body></html>
    """

    listings = OlxAdapter().parse_live_page(html)

    assert len(listings) == 1
    assert listings[0].source_id == "4mkIT"
    assert listings[0].rooms == 2
    assert listings[0].floor == 6
    assert listings[0].total_floors == 6
    assert listings[0].area_m2 == 65
    assert listings[0].district == "Яккасарайский район"
