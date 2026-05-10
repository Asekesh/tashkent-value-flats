from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Tashkent Value Flats"
    database_url: str = "sqlite:///./tashkent_flats.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    allow_live_scraping: bool = False
    seed_fixtures_on_startup: bool = False
    purge_fixture_listings_on_startup: bool = False
    enable_scrape_scheduler: bool = False
    scrape_interval_minutes: int = 15
    scheduled_scrape_sources: str = "olx"
    live_scrape_max_pages: int = 1
    live_scrape_delay_seconds: float = 2.0
    below_market_threshold: float = 0.15

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def scheduled_source_list(self) -> list[str]:
        return [source.strip() for source in self.scheduled_scrape_sources.split(",") if source.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
