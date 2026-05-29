"""alerts table for telegram-bot filter notifications

Revision ID: 0005_alerts
Revises: 0004_drop_noisy_price_events
Create Date: 2026-05-28
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_alerts"
down_revision: Union[str, None] = "0004_drop_noisy_price_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("districts", sa.Text(), nullable=True),
        sa.Column("rooms", sa.String(length=40), nullable=True),
        sa.Column("price_min", sa.Float(), nullable=True),
        sa.Column("price_max", sa.Float(), nullable=True),
        sa.Column("ppm_min", sa.Float(), nullable=True),
        sa.Column("ppm_max", sa.Float(), nullable=True),
        sa.Column("area_min", sa.Float(), nullable=True),
        sa.Column("area_max", sa.Float(), nullable=True),
        sa.Column("discount_min", sa.Float(), nullable=True),
        sa.Column("sources", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_id", "alerts", ["id"])
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_index("ix_alerts_id", table_name="alerts")
    op.drop_table("alerts")
