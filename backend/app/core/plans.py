"""Single source of truth for tariff limits.

Step 3 is infrastructure only: nothing here is enforced on the public
feed yet. `None` means "unlimited".
"""
from __future__ import annotations

from typing import Any

DEFAULT_PLAN = "free"

PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "free": {
        "listing_delay_hours": 24,
        "max_saved_filters": 1,
        "daily_listings_limit": 15,
        "notifications": False,
        "export_enabled": False,
        "analytics_level": "none",
        "api_access": False,
    },
    "pro": {
        "listing_delay_hours": 0,
        "max_saved_filters": 5,
        "daily_listings_limit": None,
        "notifications": True,
        "export_enabled": True,
        "analytics_level": "basic",
        "api_access": False,
    },
    "agent": {
        "listing_delay_hours": 0,
        "max_saved_filters": None,
        "daily_listings_limit": None,
        "notifications": True,
        "export_enabled": True,
        "analytics_level": "full",
        "api_access": True,
    },
}


def get_limits_for_plan(plan: str) -> dict[str, Any]:
    """Return a copy of the limit set for `plan`, falling back to free."""
    return dict(PLAN_LIMITS.get(plan, PLAN_LIMITS[DEFAULT_PLAN]))
