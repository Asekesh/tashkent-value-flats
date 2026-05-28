"""drop noisy price_changed events below the new threshold

Revision ID: 0004_drop_noisy_price_events
Revises: 0003_market_estimate_columns
Create Date: 2026-05-28

До введения порога каждый скрейп писал price_changed-событие, даже если цена
сдвинулась на $4 (~0.0%). Эти «прыжки» — артефакт того, что OLX/Uybor показывают
USD-эквивалент UZS-цены по своему живому курсу. Чистим всё, что не проходит
текущий порог в services/listings.py: оставляем только СНИЖЕНИЯ цены > 0.2%,
повышения и мелкие колебания удаляем.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0004_drop_noisy_price_events"
down_revision: Union[str, None] = "0003_market_estimate_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM listing_events
        WHERE event_type = 'price_changed'
          AND old_price_usd IS NOT NULL
          AND new_price_usd IS NOT NULL
          AND old_price_usd > 0
          AND (
                new_price_usd >= old_price_usd
             OR (old_price_usd - new_price_usd) <= old_price_usd * 0.002
          )
        """
    )


def downgrade() -> None:
    # Удалённые события не восстановить — это безвозвратная чистка шума.
    pass
