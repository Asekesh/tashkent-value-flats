"""add users.lang (язык интерфейса бота: ru/uz)

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
длиннее → деплой тихо падает.

Revision ID: 0014_user_lang
Revises: 0013_user_activity
Create Date: 2026-06-05
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_user_lang"
down_revision: Union[str, None] = "0013_user_activity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("lang", sa.String(2), nullable=False, server_default="ru"),
    )


def downgrade() -> None:
    op.drop_column("users", "lang")
