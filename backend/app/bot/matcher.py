from __future__ import annotations

from app.bot.i18n import DEFAULT_LANG, rooms_label, t
from app.models import Alert, Listing


def _csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [chunk.strip() for chunk in value.split(",") if chunk.strip()]


def alert_matches_listing(alert: Alert, listing: Listing) -> bool:
    """True if a freshly-seen listing fits the alert's filter."""
    if not alert.is_active:
        return False

    districts = _csv_list(alert.districts)
    if districts and listing.district not in districts:
        return False

    rooms_filter = _csv_list(alert.rooms)
    if rooms_filter:
        rooms_int = {int(r) for r in rooms_filter if r.isdigit()}
        if listing.rooms not in rooms_int:
            return False

    sources = _csv_list(alert.sources)
    if sources and listing.source not in sources:
        return False

    if alert.price_min is not None and (listing.price_usd or 0) < alert.price_min:
        return False
    if alert.price_max is not None and (listing.price_usd or 0) > alert.price_max:
        return False

    if alert.ppm_min is not None and (listing.price_per_m2_usd or 0) < alert.ppm_min:
        return False
    if alert.ppm_max is not None and (listing.price_per_m2_usd or 0) > alert.ppm_max:
        return False

    if alert.area_min is not None and (listing.area_m2 or 0) < alert.area_min:
        return False
    if alert.area_max is not None and (listing.area_m2 or 0) > alert.area_max:
        return False

    if alert.discount_min is not None:
        if listing.discount_percent is None or listing.discount_percent < alert.discount_min:
            return False

    if alert.floor_min is not None and (listing.floor or 0) < alert.floor_min:
        return False
    if alert.floor_max is not None and (listing.floor or 0) > alert.floor_max:
        return False

    return True


def describe_alert(alert: Alert, lang: str = DEFAULT_LANG) -> str:
    parts: list[str] = []
    districts = _csv_list(alert.districts)
    if districts:
        parts.append("📍 " + ", ".join(d.replace("ский район", "").replace(" район", "") for d in districts))
    else:
        parts.append("📍 " + t("da_any_district", lang))

    rooms = _csv_list(alert.rooms)
    if rooms:
        # «1/2/3к» (ru) / «1/2/3 xona» (uz): единицу берём из rooms_label.
        suffix = rooms_label(0, lang)[1:]  # отрезаем "0" → "к" / " xona"
        parts.append("🛏 " + "/".join(rooms) + suffix)

    if alert.price_min is not None or alert.price_max is not None:
        lo = f"${int(alert.price_min):,}" if alert.price_min else "—"
        hi = f"${int(alert.price_max):,}" if alert.price_max else "—"
        parts.append(f"💰 {lo}…{hi}")

    if alert.ppm_min is not None or alert.ppm_max is not None:
        lo = f"${int(alert.ppm_min)}" if alert.ppm_min else "—"
        hi = f"${int(alert.ppm_max)}" if alert.ppm_max else "—"
        parts.append(f"📐 {lo}…{hi}/м²")

    if alert.area_min is not None or alert.area_max is not None:
        lo = f"{int(alert.area_min)}" if alert.area_min else "—"
        hi = f"{int(alert.area_max)}" if alert.area_max else "—"
        parts.append(f"📏 {lo}…{hi} м²")

    if alert.floor_min is not None or alert.floor_max is not None:
        lo = str(int(alert.floor_min)) if alert.floor_min else "—"
        hi = str(int(alert.floor_max)) if alert.floor_max else "—"
        parts.append(f"🏢 {t('da_floor', lang)} {lo}…{hi}")

    if alert.discount_min is not None:
        parts.append("🎯 " + t("da_discount", lang, pct=int(alert.discount_min * 100)))

    return "\n".join(parts)
