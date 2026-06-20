"""alert deal_type + no_commission

Revision ID: 0019_alert_deal_type
Revises: 0018_listing_geo
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_alert_deal_type"
down_revision = "0018_listing_geo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column("deal_type", sa.String(length=16), server_default="sale", nullable=False),
    )
    op.add_column("alerts", sa.Column("no_commission", sa.Boolean(), nullable=True))
    op.create_index("ix_alerts_deal_type", "alerts", ["deal_type"])


def downgrade() -> None:
    op.drop_index("ix_alerts_deal_type", table_name="alerts")
    op.drop_column("alerts", "no_commission")
    op.drop_column("alerts", "deal_type")
