"""add floor_min/floor_max columns to alerts

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
длиннее → деплой тихо падает.

Revision ID: 0007_alert_floor
Revises: 0006_purge_subpercent_events
Create Date: 2026-05-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_alert_floor"
down_revision: Union[str, None] = "0006_purge_subpercent_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("floor_min", sa.Integer(), nullable=True))
    op.add_column("alerts", sa.Column("floor_max", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "floor_max")
    op.drop_column("alerts", "floor_min")
