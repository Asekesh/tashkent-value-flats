"""Классификация продавца по ОБЪЁМУ: агент вешает много объявлений под одним
аккаунтом (seller_id), собственник — одно. Надёжнее ключевых слов (агенты пишут
«собственник» в тексте, обманывая поиск) и не ломается от смены формулировок.

Принцип «на OWNER консервативно»: owner ставим только при ровно 1 активном
объявлении продавца; 2 — `unknown` (мог быть и мелкий хозяин, и агент); ≥3 — agent.

Дополнительный сигнал: если площадка САМА пометила аккаунт бизнес-аккаунтом
(`is_business`, OLX isBusiness) — это agent независимо от объёма (ловит агентств
с 1-2 объявлениями, которых счёт записал бы в owner).

Работает по строкам с непустым seller_id: Uybor userId и OLX user.id (3c-2 —
вытащили из embedded-state). realt24 (seller_id=NULL) не трогаем — у него id
продавца в выдаче нет.
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Listing

# >= этого числа активных объявлений под одним (source, seller_id) — это агент.
AGENT_LISTING_THRESHOLD = 3


def classify_sellers_by_volume(db: Session) -> dict[str, int]:
    """Проставляет seller_type ('agent'|'owner'|'unknown') по числу активных
    объявлений продавца (+ бизнес-флаг площадки). Возвращает счётчик ПРОДАВЦОВ."""
    counts = db.execute(
        select(Listing.source, Listing.seller_id, func.count())
        .where(Listing.status == "active", Listing.seller_id.is_not(None))
        .group_by(Listing.source, Listing.seller_id)
    ).all()
    # Продавцы, помеченные площадкой как бизнес — agent независимо от объёма.
    business = {
        tuple(row)
        for row in db.execute(
            select(Listing.source, Listing.seller_id)
            .where(
                Listing.status == "active",
                Listing.seller_id.is_not(None),
                Listing.is_business.is_(True),
            )
            .distinct()
        ).all()
    }

    stats = {"agent": 0, "owner": 0, "unknown": 0}
    for source, seller_id, n in counts:
        if (source, seller_id) in business or n >= AGENT_LISTING_THRESHOLD:
            label = "agent"
        elif n == 1:
            label = "owner"
        else:
            label = "unknown"
        db.execute(
            update(Listing)
            .where(Listing.source == source, Listing.seller_id == seller_id)
            .values(seller_type=label)
        )
        stats[label] += 1
    db.commit()
    return stats
