from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.models import Listing
from app.services.seller_classifier import classify_sellers_by_volume


def _mk(source_id: str, seller_id: str, *, source: str = "uybor", is_business: bool | None = None) -> Listing:
    return Listing(
        source=source, source_id=source_id, url="u", title="t", price=500, currency="USD",
        price_usd=500, area_m2=50, price_per_m2_usd=10, rooms=2, district="d", address_raw="a",
        photos="[]", status="active", duplicate_group_key=source_id, source_urls="[]",
        deal_type="rent", price_period="month", seller_id=seller_id, is_business=is_business,
        seen_at=datetime.utcnow(), market_sample_size=0, is_below_market=False, duplicate_count=1,
    )


def test_classify_sellers_by_volume(db_session):
    # 3 объявления под одним аккаунтом -> agent; 1 -> owner; 2 -> unknown (на owner консервативно).
    for i in range(3):
        db_session.add(_mk(f"A{i}", "acc_agent"))
    db_session.add(_mk("O1", "acc_owner"))
    for i in range(2):
        db_session.add(_mk(f"U{i}", "acc_two"))
    db_session.commit()

    stats = classify_sellers_by_volume(db_session)
    assert stats == {"agent": 1, "owner": 1, "unknown": 1}  # счёт ПРОДАВЦОВ

    types = {l.source_id: l.seller_type for l in db_session.scalars(select(Listing)).all()}
    assert all(types[f"A{i}"] == "agent" for i in range(3))
    assert types["O1"] == "owner"
    assert all(types[f"U{i}"] == "unknown" for i in range(2))


def test_classify_ignores_null_seller_id(db_session):
    # OLX/realt24 без seller_id не трогаем (для них seller_type определяется иначе).
    olx = _mk("X1", "acc_agent")
    olx.source = "olx"
    olx.seller_id = None
    olx.seller_type = "preset"
    db_session.add(olx)
    db_session.commit()

    classify_sellers_by_volume(db_session)
    assert db_session.scalar(select(Listing.seller_type).where(Listing.source_id == "X1")) == "preset"


def test_classify_olx_by_seller_id(db_session):
    # OLX теперь несёт seller_id (user.id) → классификатор по объёму накрывает и его.
    for i in range(3):
        db_session.add(_mk(f"OA{i}", "olx_agent", source="olx"))
    db_session.add(_mk("OO1", "olx_owner", source="olx"))
    db_session.commit()

    classify_sellers_by_volume(db_session)
    types = {l.source_id: l.seller_type for l in db_session.scalars(select(Listing)).all()}
    assert all(types[f"OA{i}"] == "agent" for i in range(3))
    assert types["OO1"] == "owner"


def test_business_flag_forces_agent(db_session):
    # Бизнес-аккаунт с 1 объявлением: объём сказал бы owner, но isBusiness → agent.
    db_session.add(_mk("B1", "biz_one", source="olx", is_business=True))
    db_session.commit()

    stats = classify_sellers_by_volume(db_session)
    assert stats == {"agent": 1, "owner": 0, "unknown": 0}
    assert db_session.scalar(select(Listing.seller_type).where(Listing.source_id == "B1")) == "agent"
