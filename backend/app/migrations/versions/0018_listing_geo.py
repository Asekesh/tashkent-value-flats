"""add geo columns (lat/lng/coords_precision) + bbox index for the map view

NB: revision id ≤ 32 символов — alembic_version.version_num на проде VARCHAR(32);
длиннее → деплой тихо падает. "0018_listing_geo" = 16 символов.

Колонки nullable, без server_default → ALTER мгновенный, ~11.7k строк не
переписываются, прод не блокируется. Старые строки и Realt24 (координат нет)
остаются NULL и просто не показываются на карте; lat/lng наливаются при
повторном проходе объявления через парсер (Uybor — точные, OLX — размытые).

coords_precision: 'exact' (Uybor) | 'approx' (OLX, show_detailed всегда False,
размытие ~2-5 км) | NULL (неизвестно). Уважается на карте и в дедупе.

Индекс (lat, lng) — обычный B-tree (PostGIS на Railway НЕТ). Для bbox-запроса
`lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?` ведущая lat даёт Index Scan вместо
Seq Scan по всей таблице.

Revision ID: 0018_listing_geo
Revises: 0017_olx_business
Create Date: 2026-06-06
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_listing_geo"
down_revision: Union[str, None] = "0017_olx_business"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("listings", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column("listings", sa.Column("coords_precision", sa.String(8), nullable=True))  # 'exact'|'approx'|NULL
    # Составной B-tree под bbox: ведущая lat закрывает диапазон по широте,
    # lng — добор. На обоих диалектах (Postgres прод / SQLite dev) одинаково.
    op.create_index("ix_listings_lat_lng", "listings", ["lat", "lng"])


def downgrade() -> None:
    # Индекс дропаем ПЕРВЫМ — он висит на колонках, которые удаляем следом.
    op.drop_index("ix_listings_lat_lng", table_name="listings")
    op.drop_column("listings", "coords_precision")
    op.drop_column("listings", "lng")
    op.drop_column("listings", "lat")
