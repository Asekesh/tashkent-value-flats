from __future__ import annotations

from pathlib import Path

from app.scrapers.adapters.olx import OlxAdapter, OlxRentAdapter
from app.scrapers.adapters.realt24 import Realt24Adapter
from app.scrapers.adapters.uybor import UyborAdapter, UyborRentAdapter
from app.scrapers.base import RawListing, SourceAdapter


# Ключ реестра = «джоб» (площадка × тип сделки). Listing.source при этом остаётся
# платформой ('olx'/'uybor') — её ставит сам адаптер, см. .source. Так публичная
# выдача/метки/архивный свип группируются по площадке, а скрейп-раны и parser-health
# в /admin видят аренду отдельным джобом. realt24 — пока только продажа
# (их API не отделяет аренду).
ADAPTERS: dict[str, SourceAdapter] = {
    "olx": OlxAdapter(),
    "uybor": UyborAdapter(),
    "realt24": Realt24Adapter(),
    "olx_rent": OlxRentAdapter(),
    "uybor_rent": UyborRentAdapter(),
}


def get_adapter(source: str) -> SourceAdapter:
    try:
        return ADAPTERS[source]
    except KeyError as exc:
        raise ValueError(f"Unknown source: {source}") from exc


def parse_fixture(source: str) -> list[RawListing]:
    adapter = get_adapter(source)
    fixture_path = Path(__file__).parent / "fixtures" / adapter.fixture_name
    html = fixture_path.read_text(encoding="utf-8")
    return adapter.parse(html)
