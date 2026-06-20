from app.bot.matcher import alert_matches_listing
from app.models import Alert, Listing


def _listing(**kw):
    base = dict(
        source="uybor", source_id="x", url="http://x", title="t",
        price=500.0, currency="USD",
        district="Юнусабадский район", rooms=2, price_usd=500.0,
        area_m2=50.0, floor=3, status="active", deal_type="sale",
        commission_pct=None, discount_percent=None, price_per_m2_usd=10.0,
        address_raw="", duplicate_group_key="x",
    )
    base.update(kw)
    return Listing(**base)


def _alert(**kw):
    base = dict(name="a", deal_type="sale", is_active=True)
    base.update(kw)
    return Alert(**base)


def test_sale_alert_rejects_rent_listing():
    alert = _alert(deal_type="sale")
    listing = _listing(deal_type="rent", price_usd=500.0)
    assert alert_matches_listing(alert, listing) is False


def test_rent_alert_rejects_sale_listing():
    alert = _alert(deal_type="rent")
    listing = _listing(deal_type="sale")
    assert alert_matches_listing(alert, listing) is False


def test_rent_alert_matches_rent_listing():
    alert = _alert(deal_type="rent", price_max=700.0)
    listing = _listing(deal_type="rent", price_usd=500.0)
    assert alert_matches_listing(alert, listing) is True


def test_no_commission_filter_rejects_commissioned():
    alert = _alert(deal_type="rent", no_commission=True)
    listing = _listing(deal_type="rent", commission_pct=50.0)
    assert alert_matches_listing(alert, listing) is False


def test_no_commission_filter_rejects_unknown_commission():
    alert = _alert(deal_type="rent", no_commission=True)
    listing = _listing(deal_type="rent", commission_pct=None)
    assert alert_matches_listing(alert, listing) is False


def test_no_commission_filter_accepts_zero_commission():
    alert = _alert(deal_type="rent", no_commission=True)
    listing = _listing(deal_type="rent", commission_pct=0.0)
    assert alert_matches_listing(alert, listing) is True


def test_no_commission_none_ignores_commission():
    alert = _alert(deal_type="rent", no_commission=None)
    listing = _listing(deal_type="rent", commission_pct=50.0)
    assert alert_matches_listing(alert, listing) is True
