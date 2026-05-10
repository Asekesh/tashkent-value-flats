from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Tashkent Value Flats"
    database_url: str = "sqlite:///./tashkent_flats.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    allow_live_scraping: bool = False
    seed_fixtures_on_startup: bool = False
    below_market_threshold: float = 0.15

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
