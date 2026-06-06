"""add listings.is_business (площадка пометила бизнес-аккаунт → агент)

NB: revision id ≤ 32 символов. "0017_olx_business" = 17.

OLX отдаёт isBusiness на каждом объявлении: бизнес-аккаунт = агентство/риелтор.
Классификатор форсит seller_type='agent' для таких продавцов независимо от объёма
(ловит агентств с 1-2 объявлениями, которых счёт записал бы в owner).

Revision ID: 0017_olx_business
Revises: 0016_seller_id
Create Date: 2026-06-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_olx_business"
down_revision: Union[str, None] = "0016_seller_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("is_business", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("listings", "is_business")
