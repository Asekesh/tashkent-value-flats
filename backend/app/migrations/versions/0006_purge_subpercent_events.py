"""drop price_changed events below the new 1% threshold

Revision ID: 0006_purge_subpercent_events
Revises: 0005_alerts
Create Date: 2026-05-29

Порог значимого снижения цены подняли с 0.2% до 1% (services/listings.py),
т.к. остались мелкие перепады <1%, которые тоже курсовой шум. Чистим всё,
что не проходит новый порог: оставляем только СНИЖЕНИЯ цены > 1%.

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
исходное имя 0006_purge_subpercent_price_events (34) валило `alembic upgrade head`.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0006_purge_subpercent_events"
down_revision: Union[str, None] = "0005_alerts"
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
             OR (old_price_usd - new_price_usd) <= old_price_usd * 0.01
          )
        """
    )


def downgrade() -> None:
    # Удалённые события не восстановить — это безвозвратная чистка шума.
    pass
