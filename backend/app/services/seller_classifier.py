"""Классификация продавца по ОБЪЁМУ: агент вешает много объявлений под одним
аккаунтом (seller_id), собственник — одно. Надёжнее ключевых слов (агенты пишут
«собственник» в тексте, обманывая поиск) и не ломается от смены формулировок.

Принцип «на OWNER консервативно»: owner ставим только при ровно 1 активном
объявлении продавца; 2 — `unknown` (мог быть и мелкий хозяин, и агент); ≥3 — agent.

Работает только по строкам с непустым seller_id (сейчас Uybor userId). OLX/realt24
(seller_id=NULL) не трогаем — для них seller_type определяется иначе/позже (3c-2).
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Listing

# >= этого числа активных объявлений под одним (source, seller_id) — это агент.
AGENT_LISTING_THRESHOLD = 3


def classify_sellers_by_volume(db: Session) -> dict[str, int]:
    """Проставляет seller_type ('agent'|'owner'|'unknown') по числу активных
    объявлений продавца. Возвращает счётчик ПРОДАВЦОВ по категориям."""
    counts = db.execute(
        select(Listing.source, Listing.seller_id, func.count())
        .where(Listing.status == "active", Listing.seller_id.is_not(None))
        .group_by(Listing.source, Listing.seller_id)
    ).all()

    stats = {"agent": 0, "owner": 0, "unknown": 0}
    for source, seller_id, n in counts:
        if n >= AGENT_LISTING_THRESHOLD:
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
