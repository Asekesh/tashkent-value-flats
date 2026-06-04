"""add users.last_seen_at + users.source (активность + атрибуция источника)

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
длиннее → деплой тихо падает.

Revision ID: 0010_user_source_seen
Revises: 0009_feedback_reply
Create Date: 2026-06-04
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_user_source_seen"
down_revision: Union[str, None] = "0009_feedback_reply"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("source", sa.String(64), nullable=True))
    op.create_index("ix_users_last_seen_at", "users", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_users_last_seen_at", table_name="users")
    op.drop_column("users", "source")
    op.drop_column("users", "last_seen_at")
