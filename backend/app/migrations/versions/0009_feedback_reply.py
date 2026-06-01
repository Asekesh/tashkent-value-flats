"""add admin_reply/replied_at to feedback (ответы из админки)

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
длиннее → деплой тихо падает.

Revision ID: 0009_feedback_reply
Revises: 0008_feedback
Create Date: 2026-06-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_feedback_reply"
down_revision: Union[str, None] = "0008_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("admin_reply", sa.Text(), nullable=True))
    op.add_column("feedback", sa.Column("replied_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback", "replied_at")
    op.drop_column("feedback", "admin_reply")
