from __future__ import annotations

from app.scrapers.adapters.common import parse_fixture_cards
from app.scrapers.base import RawListing, SourceAdapter


class UyborAdapter(SourceAdapter):
    source = "uybor"
    fixture_name = "uybor.html"

    def parse(self, html: str) -> list[RawListing]:
        return parse_fixture_cards(html, self.source)
