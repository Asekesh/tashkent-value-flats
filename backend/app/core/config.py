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
    scheduled_scrape_sources: str = "olx,uybor,realt24"
    scheduled_scrape_mode: str = "quick"
    live_scrape_max_pages: int = 1
    live_scrape_delay_seconds: float = 2.0
    quick_known_stop_threshold: int = 50
    min_listing_price_usd: float = 5000.0
    min_listing_price_per_m2_usd: float = 100.0
    below_market_threshold: float = 0.15

    # --- Auth (Telegram login + JWT session) ---
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    jwt_secret: str = "dev-insecure-secret-change-me"
    jwt_ttl_hours: int = 720
    jwt_cookie_name: str = "tvf_session"
    cookie_secure: bool = True
    admin_telegram_ids: str = ""

    # --- Registration gate (Step 5) ---
    # After the prompt is dismissed once, re-show it no more often than
    # every N meaningful actions (filter / sort / open card).
    reg_gate_prompt_every: int = 3

    # --- Legal pages (Step 7) ---
    # Contact for listing-removal requests; shown on /removal when set.
    legal_contact_email: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def admin_telegram_id_set(self) -> set[int]:
        ids: set[int] = set()
        for chunk in self.admin_telegram_ids.split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                ids.add(int(chunk))
        return ids

    @property
    def scheduled_source_list(self) -> list[str]:
        return [source.strip() for source in self.scheduled_scrape_sources.split(",") if source.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
