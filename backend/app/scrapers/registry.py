from __future__ import annotations

from pathlib import Path

from app.scrapers.adapters.olx import OlxAdapter
from app.scrapers.adapters.realt24 import Realt24Adapter
from app.scrapers.adapters.uybor import UyborAdapter
from app.scrapers.base import RawListing, SourceAdapter


ADAPTERS: dict[str, SourceAdapter] = {
    "olx": OlxAdapter(),
    "uybor": UyborAdapter(),
    "realt24": Realt24Adapter(),
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
