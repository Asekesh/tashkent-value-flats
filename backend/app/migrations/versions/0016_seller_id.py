"""add listings.seller_id (id продавца у площадки — для детекции агентов по объёму)

NB: revision id ≤ 32 символов. "0016_seller_id" = 14.

Uybor отдаёт userId; агент вешает десятки объявлений под одним userId, собственник —
одно. Классификатор seller_type считает активные объявления на (source, seller_id).

Revision ID: 0016_seller_id
Revises: 0015_rental_fields
Create Date: 2026-06-05
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_seller_id"
down_revision: Union[str, None] = "0015_rental_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("seller_id", sa.String(80), nullable=True))
    # Композитный индекс под запрос «сколько активных у этого продавца на площадке».
    op.create_index("ix_listings_source_seller", "listings", ["source", "seller_id"])


def downgrade() -> None:
    op.drop_index("ix_listings_source_seller", table_name="listings")
    op.drop_column("listings", "seller_id")
