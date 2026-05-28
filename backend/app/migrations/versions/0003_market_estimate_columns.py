"""market estimate cache on listings table

Revision ID: 0003_market_estimate_columns
Revises: 0002_onboarding_flag
Create Date: 2026-05-28

Кеш строгой оценки рынка на каждом листинге. До этой миграции дисконт
считался live на каждый запрос /listings через build_market_index — на
11700 листингов это тяжело и в индексе нет строгих фильтров (материал,
год, микро-локация). Теперь оценка считается один раз при upsert и
ночью батчем; API читает столбцы напрямую.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_market_estimate_columns"
down_revision: Union[str, None] = "0002_onboarding_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("listings") as batch_op:
        batch_op.add_column(sa.Column("market_price_per_m2_usd", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("market_basis", sa.String(length=40), nullable=True))
        batch_op.add_column(
            sa.Column("market_sample_size", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("market_confidence", sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column("discount_percent", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("is_below_market", sa.Boolean(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("savings_usd", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("market_calculated_at", sa.DateTime(), nullable=True))
    op.create_index("ix_listings_discount_percent", "listings", ["discount_percent"])
    op.create_index("ix_listings_is_below_market", "listings", ["is_below_market"])


def downgrade() -> None:
    op.drop_index("ix_listings_is_below_market", table_name="listings")
    op.drop_index("ix_listings_discount_percent", table_name="listings")
    with op.batch_alter_table("listings") as batch_op:
        batch_op.drop_column("market_calculated_at")
        batch_op.drop_column("savings_usd")
        batch_op.drop_column("is_below_market")
        batch_op.drop_column("discount_percent")
        batch_op.drop_column("market_confidence")
        batch_op.drop_column("market_sample_size")
        batch_op.drop_column("market_basis")
        batch_op.drop_column("market_price_per_m2_usd")
