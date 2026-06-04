"""add limit_events table (лог упёршихся в лимит — лид-лист на платник)

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
длиннее → деплой тихо падает.

Revision ID: 0011_limit_events
Revises: 0010_user_source_seen
Create Date: 2026-06-04
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_limit_events"
down_revision: Union[str, None] = "0010_user_source_seen"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "limit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("plan", sa.String(length=16), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_limit_events_user_id", "limit_events", ["user_id"])
    op.create_index("ix_limit_events_event_type", "limit_events", ["event_type"])
    op.create_index("ix_limit_events_at", "limit_events", ["at"])


def downgrade() -> None:
    op.drop_index("ix_limit_events_at", table_name="limit_events")
    op.drop_index("ix_limit_events_event_type", table_name="limit_events")
    op.drop_index("ix_limit_events_user_id", table_name="limit_events")
    op.drop_table("limit_events")
