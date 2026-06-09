import json

from app.scrapers.registry import parse_fixture
from app.scrapers.adapters.olx import OlxAdapter, _detail_is_archived, _yesno_to_bool
from app.scrapers.adapters.realt24 import Realt24Adapter
from app.scrapers.adapters.uybor import UyborAdapter, _furnished_from_text
from app.services.normalization import price_per_m2, to_usd


def _olx_detail_html(status: str, is_active: bool) -> str:
    state = {"ad": {"ad": {"status": status, "isActive": is_active, "photos": []}}}
    blob = json.dumps(json.dumps(state))
    return f"<html><body><script>window.__PRERENDERED_STATE__ = {blob};</script></body></html>"


def test_olx_detail_archived_state_detected():
    assert _detail_is_archived(_olx_detail_html("outdated", False)) is True
    assert _detail_is_archived(_olx_detail_html("removed_by_user", False)) is True
    assert _detail_is_archived(_olx_detail_html("active", True)) is False
    assert _detail_is_archived("<html><body>no state here</body></html>") is False


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


def test_uybor_furnished_from_text_handles_negation():
    # Положительные формулировки → True
    assert _furnished_from_text("Сдается квартира с мебелью") is True
    assert _furnished_from_text("Меблированная, заходи и живи") is True
    assert _furnished_from_text("вся мебель остается") is True
    # Отрицание (в т.ч. слитное/раздельное «не меблир…») → False
    assert _furnished_from_text("квартира без мебели") is False
    assert _furnished_from_text("Сдается немеблированная квартира") is False
    assert _furnished_from_text("Квартира НЕ меблирована") is False
    assert _furnished_from_text("не-меблированная") is False
    # Нет явного сигнала / пусто → None (не выдумываем)
    assert _furnished_from_text("Чистая квартира, евроремонт") is None
    assert _furnished_from_text("") is None
    assert _furnished_from_text(None) is None


def test_olx_yesno_to_bool():
    assert _yesno_to_bool("yes") is True
    assert _yesno_to_bool("no") is False
    assert _yesno_to_bool("YES") is True
    assert _yesno_to_bool(None) is None
    assert _yesno_to_bool("") is None
    assert _yesno_to_bool("да") is None  # OLX отдаёт только yes/no, не локализованное


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


def test_olx_live_parser_dedupes_jsonld_and_card_for_same_ad():
    # Same OLX ad appears in both JSON-LD (URL slug id) and the HTML card grid
    # (used to expose card[id] numeric DB id). Both must produce the same
    # source_id so parse_live_page yields one RawListing — otherwise the ad is
    # ingested twice and shows up as a duplicate in the dashboard.
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
              "url": "https://www.olx.uz/d/obyavlenie/test-ID4mkIT.html"
            }
          ]
        }
      }
      </script>
      <div data-cy="l-card" id="64461800">
        <a href="https://www.olx.uz/d/obyavlenie/test-ID4mkIT.html">
          <h4>Яккасарай 2/6/6 65м2 евро люкс</h4>
        </a>
        <p data-testid="ad-price">1 028 312 999 сум</p>
        <p data-testid="location-date">Ташкент, Яккасарайский район — Сегодня</p>
      </div>
    </body></html>
    """

    listings = OlxAdapter().parse_live_page(html)

    assert len(listings) == 1
    assert listings[0].source_id == "4mkIT"


def test_uybor_api_parser_extracts_listing_fields():
    payload = {
        "total": 1,
        "results": [
            {
                "id": 1312605,
                "operationType": "sale",
                "categoryId": 7,
                "description": "Продается 2-комнатная квартира. Площадь 64 м².",
                "price": 105000,
                "priceCurrency": "usd",
                "address": "жилой комплекс Паркент Авеню",
                "districtId": 196,
                "room": "2",
                "square": 64,
                "floor": 7,
                "floorTotal": 9,
                "media": [{"url": "https://api.uybor.uz/api/v1/media/n/test.jpg"}],
                "moderationStatus": "approved",
                "isActive": True,
                "upAt": "2026-05-11T10:02:25.955Z",
            }
        ],
    }

    listings = UyborAdapter().parse_api_page(payload, location_names={196: "Мирзо-Улугбекский район"})

    assert len(listings) == 1
    assert listings[0].source == "uybor"
    assert listings[0].source_id == "1312605"
    assert listings[0].url == "https://uybor.uz/listings/1312605"
    assert listings[0].rooms == 2
    assert listings[0].area_m2 == 64
    assert listings[0].floor == 7
    assert listings[0].total_floors == 9
    assert listings[0].currency == "USD"
    assert listings[0].district == "Мирзо-Улугбекский район"
    assert listings[0].photos == ["https://api.uybor.uz/api/v1/media/n/test.jpg"]


def test_uybor_api_parser_uses_total_price_when_price_is_per_sqm():
    payload = {
        "total": 1,
        "results": [
            {
                "id": 1310938,
                "operationType": "sale",
                "categoryId": 7,
                "description": "ойлага берилади урикзор бозор йонида янги хали",
                "price": 400,
                "priceCurrency": "usd",
                "priceType": "sqm",
                "prices": {"usd": 22400, "uzs": 271375328},
                "address": "улица Юсуфа Саккокий",
                "districtId": 203,
                "room": "2",
                "square": 56,
                "floor": 6,
                "floorTotal": 16,
                "moderationStatus": "approved",
                "isActive": True,
            }
        ],
    }

    listings = UyborAdapter().parse_api_page(payload, location_names={203: "Учтепинский район"})

    assert len(listings) == 1
    assert listings[0].price == 22400
    assert listings[0].currency == "USD"
    assert listings[0].area_m2 == 56


def test_realt24_api_parser_extracts_listing_fields():
    payload = {
        "data": [
            {
                "id": "20197",
                "type": "Property",
                "attributes": {
                    "name": {"ru": "4-комнатная квартира − 150 м², 4/5 этаж"},
                    "statusKey": "active",
                    "price": {"usd": 310000, "uzs": 3755640700},
                    "currency": "usd",
                    "description": {"ru": "Продается просторная квартира"},
                    "imageSets": [{"w600": "https://storage.realt24.uz/files/test.w600.webp"}],
                    "publishedAt": "2025-10-07T17:31:02.92566+00:00",
                },
                "relations": {
                    "address": {
                        "data": {
                            "attributes": {
                                "fullAddress": {
                                    "ru": "Ташкент, Мирзо-Улугбекский район, улица Льва Толстого, 63"
                                }
                            }
                        }
                    },
                    "user": {
                        "data": {
                            "relations": {
                                "role": {"data": {"attributes": {"key": "owner"}}}
                            }
                        }
                    },
                },
            }
        ],
        "meta": {"hasNext": False},
    }

    listings = Realt24Adapter().parse_api_page(payload)

    assert len(listings) == 1
    assert listings[0].source == "realt24"
    assert listings[0].source_id == "20197"
    assert listings[0].url == "https://realt24.uz/ru/listing/20197/"
    assert listings[0].rooms == 4
    assert listings[0].area_m2 == 150
    assert listings[0].floor == 4
    assert listings[0].total_floors == 5
    assert listings[0].district == "Мирзо-Улугбекский район"
    assert listings[0].seller_type == "owner"
    assert listings[0].photos == ["https://storage.realt24.uz/files/test.w600.webp"]
