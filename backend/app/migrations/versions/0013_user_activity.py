"""add user_activity table (по дню активности — основа ретеншна и DAU/WAU/MAU)

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
длиннее → деплой тихо падает.

Revision ID: 0013_user_activity
Revises: 0012_alert_sends
Create Date: 2026-06-04
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_user_activity"
down_revision: Union[str, None] = "0012_alert_sends"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_activity",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
    )
    op.create_index("ix_user_activity_day", "user_activity", ["day"])


def downgrade() -> None:
    op.drop_index("ix_user_activity_day", table_name="user_activity")
    op.drop_table("user_activity")
