"""add rental fields (deal_type/price_period/is_furnished/commission_pct/ЖК) + residential_complex

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
длиннее → деплой тихо падает. "0015_rental_fields" = 18 символов.

seller_type СОЗНАТЕЛЬНО не добавляется — колонка уже есть в listings (String(80)).

deal_type бэкфиллится в 'sale' и хранит server_default='sale', поэтому
существующие ~11.7k строк и старый парсер продажи (он deal_type не выставляет)
продолжают быть/писать 'sale' без изменений — раздел «Купить» не затрагивается.
Аренду step 3 пишет явным 'rent'.

Revision ID: 0015_rental_fields
Revises: 0014_user_lang
Create Date: 2026-06-05
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_rental_fields"
down_revision: Union[str, None] = "0014_user_lang"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Справочник ЖК. Парсер апсертит по match_key — нормализованному ключу,
    #    чтобы «Mirabad Avenue / Мирабад Авеню / mirabad avenue» схлопывались в
    #    одну строку, а не плодили дубли. Создаём ДО FK-колонки на listings.
    #    UniqueConstraint объявляем ВНУТРИ create_table (часть CREATE TABLE), а не
    #    отдельным op.create_unique_constraint — иначе SQLite (локальный dev) падает:
    #    «No support for ALTER of constraints». В CREATE TABLE работает на обоих диалектах.
    op.create_table(
        "residential_complex",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),       # каноничное имя для показа
        sa.Column("match_key", sa.String(255), nullable=False),  # нормализованный ключ склейки
        sa.Column("district", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("match_key", name="uq_residential_complex_match_key"),
    )

    # 2) Новые колонки listings. deal_type — NOT NULL c server_default='sale'
    #    (бэкфилл существующих строк + безопасная вставка старого парсера).
    #    Дефолт НЕ снимаем: защитная сетка, аренда всё равно пишется явным 'rent'.
    op.add_column(
        "listings",
        sa.Column("deal_type", sa.String(16), nullable=False, server_default="sale"),
    )
    op.add_column("listings", sa.Column("price_period", sa.String(16), nullable=True))      # 'month'/'day'; NULL для продажи
    op.add_column("listings", sa.Column("is_furnished", sa.Boolean(), nullable=True))       # фильтр аренды; NULL=неизвестно
    op.add_column("listings", sa.Column("commission_pct", sa.Numeric(5, 2), nullable=True)) # NULL=неизвестно, 0=без комиссии

    # residential_complex_id: на Postgres (прод) — с настоящим FK + ON DELETE SET NULL;
    # на SQLite (dev) FK к существующей таблице через ALTER невозможен без пересборки
    # всей таблицы, поэтому там добавляем просто колонку. ORM-relation объявлен в модели.
    if op.get_bind().dialect.name == "postgresql":
        op.add_column(
            "listings",
            sa.Column(
                "residential_complex_id",
                sa.Integer(),
                sa.ForeignKey("residential_complex.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    else:
        op.add_column("listings", sa.Column("residential_complex_id", sa.Integer(), nullable=True))
    # опционально — удали эти две строки (и в downgrade, и в модели), если парсер не тянет:
    op.add_column("listings", sa.Column("deposit", sa.Numeric(14, 2), nullable=True))
    op.add_column("listings", sa.Column("utilities_included", sa.Boolean(), nullable=True))

    # 3) Индексы под горячие пути: фильтр вкладки sale/rent и джойн по ЖК.
    op.create_index("ix_listings_deal_type", "listings", ["deal_type"])
    op.create_index("ix_listings_residential_complex_id", "listings", ["residential_complex_id"])


def downgrade() -> None:
    op.drop_index("ix_listings_residential_complex_id", table_name="listings")
    op.drop_index("ix_listings_deal_type", table_name="listings")
    op.drop_column("listings", "utilities_included")
    op.drop_column("listings", "deposit")
    op.drop_column("listings", "residential_complex_id")  # снимет и inline FK
    op.drop_column("listings", "commission_pct")
    op.drop_column("listings", "is_furnished")
    op.drop_column("listings", "price_period")
    op.drop_column("listings", "deal_type")
    op.drop_table("residential_complex")
