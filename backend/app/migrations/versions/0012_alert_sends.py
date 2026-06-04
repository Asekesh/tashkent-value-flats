"""add alert_sends table (лог отправок + клики = CTR алёртов)

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
длиннее → деплой тихо падает.

Revision ID: 0012_alert_sends
Revises: 0011_limit_events
Create Date: 2026-06-04
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_alert_sends"
down_revision: Union[str, None] = "0011_limit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_sends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "alert_id",
            sa.Integer(),
            sa.ForeignKey("alerts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("discount_snapshot", sa.Float(), nullable=True),
        sa.Column("district", sa.String(length=120), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("clicked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_alert_sends_alert_id", "alert_sends", ["alert_id"])
    op.create_index("ix_alert_sends_user_id", "alert_sends", ["user_id"])
    op.create_index("ix_alert_sends_listing_id", "alert_sends", ["listing_id"])
    op.create_index("ix_alert_sends_sent_at", "alert_sends", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_alert_sends_sent_at", table_name="alert_sends")
    op.drop_index("ix_alert_sends_listing_id", table_name="alert_sends")
    op.drop_index("ix_alert_sends_user_id", table_name="alert_sends")
    op.drop_index("ix_alert_sends_alert_id", table_name="alert_sends")
    op.drop_table("alert_sends")
