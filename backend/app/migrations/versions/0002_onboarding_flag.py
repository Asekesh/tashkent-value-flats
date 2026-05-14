"""onboarding flag: users.has_seen_onboarding

Revision ID: 0002_onboarding_flag
Revises: 0001_auth_tables
Create Date: 2026-05-14

Adds a single boolean column to the existing `users` table. No tables are
dropped or recreated; existing rows default to has_seen_onboarding = false.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_onboarding_flag"
down_revision: Union[str, None] = "0001_auth_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "has_seen_onboarding",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("has_seen_onboarding")
