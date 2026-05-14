"""auth tables: users, subscriptions, login_events

Revision ID: 0001_auth_tables
Revises:
Create Date: 2026-05-14

Adds authentication / subscription infrastructure. Only creates NEW tables;
existing tables (listings, scrape_runs, ...) are untouched.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_auth_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=120), nullable=True),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("photo_url", sa.String(length=512), nullable=True),
        sa.Column(
            "role",
            sa.Enum("user", "admin", name="user_role", native_enum=False),
            server_default="user",
            nullable=False,
        ),
        sa.Column(
            "account_type",
            sa.Enum("individual", "agent", name="account_type", native_enum=False),
            server_default="individual",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.create_index("ix_users_account_type", "users", ["account_type"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "plan",
            sa.Enum("free", "pro", "agent", name="subscription_plan", native_enum=False),
            server_default="free",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active", "expired", "cancelled",
                name="subscription_status", native_enum=False,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscriptions_id", "subscriptions", ["id"])
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])

    op.create_table(
        "login_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_events_id", "login_events", ["id"])
    op.create_index("ix_login_events_user_id", "login_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_login_events_user_id", table_name="login_events")
    op.drop_index("ix_login_events_id", table_name="login_events")
    op.drop_table("login_events")

    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index("ix_users_account_type", table_name="users")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
