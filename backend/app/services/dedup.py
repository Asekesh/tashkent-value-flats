"""One-shot cleanup of legacy duplicate listings.

Two failure modes produced the dupes that linger in prod:
1. OLX scraper used to ingest each ad twice (JSON-LD URL slug vs HTML card
   numeric ``id``), so identical rows ended up with different ``source_id`` and
   slipped past the in-parser ``seen`` set.
2. The same physical flat reposted with a slightly tweaked title/price (e.g.
   one agent at $117k, another at $119k) — different hashed fingerprints, so
   ``find_duplicate`` returned ``None``.

Pass 1 collapses exact-field groups unconditionally. Pass 2 catches reposts
priced within ``LOOSE_DEDUP_PRICE_TOLERANCE`` of each other in the same
district / rooms / area bucket — floor is checked for compatibility (None
treated as a wildcard against a single known floor) but no longer required,
since OLX cards often omit the floor field on one of the reposts.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Listing
from app.services.listings import LOOSE_DEDUP_PRICE_TOLERANCE, merge_source_urls
from app.services.normalization import dumps_json, loads_json


def merge_existing_duplicates(db: Session, dry_run: bool = False) -> dict:
    rows = list(db.scalars(select(Listing)).all())
    dropped: set[int] = set()
    merged_groups = 0
    deleted_rows = 0

    # Pass 1: exact-field dupes (identical price + area + currency).
    exact_groups: dict[tuple, list[Listing]] = defaultdict(list)
    for listing in rows:
        key = (
            listing.deal_type,  # аренду и продажу не кластеризуем вместе (source общий)
            listing.source,
            listing.district,
            listing.rooms,
            listing.area_m2,
            listing.price,
            listing.currency,
        )
        exact_groups[key].append(listing)

    for listings in exact_groups.values():
        if len(listings) < 2:
            continue
        canonical, extras = _merge_cluster(listings, db, dry_run)
        dropped.update(extra.id for extra in extras)
        merged_groups += 1
        deleted_rows += len(extras)

    # Pass 2: same-flat reposts with a slight price drift. Skip anything that
    # pass 1 already dropped so a row isn't counted (or deleted) twice. Bucket
    # by district / rooms / area only — floor is no longer part of the key
    # because OLX cards routinely lose the floor field on a repost.
    flat_buckets: dict[tuple, list[Listing]] = defaultdict(list)
    for listing in rows:
        if listing.id in dropped:
            continue
        if listing.area_m2 is None or listing.rooms is None:
            continue
        key = (
            listing.deal_type,  # см. Pass 1: аренда и продажа — разные кластеры
            listing.source,
            listing.district,
            listing.rooms,
            listing.area_m2,
        )
        flat_buckets[key].append(listing)

    for listings in flat_buckets.values():
        if len(listings) < 2:
            continue
        for cluster in _cluster_by_price(listings):
            if len(cluster) < 2:
                continue
            for sub_cluster in _split_by_floor(cluster):
                if len(sub_cluster) < 2:
                    continue
                _, extras = _merge_cluster(sub_cluster, db, dry_run)
                dropped.update(extra.id for extra in extras)
                merged_groups += 1
                deleted_rows += len(extras)

    if not dry_run:
        db.commit()

    return {
        "merged_groups": merged_groups,
        "deleted_rows": deleted_rows,
        "dry_run": dry_run,
    }


def _split_by_floor(cluster: list[Listing]) -> list[list[Listing]]:
    """Split a price cluster into sub-clusters compatible by floor.

    None-floor rows are ambiguous: when the cluster has at most one known
    floor, they're attributed to it (or to the all-None group) and everyone
    merges. When the cluster contains two or more distinct known floors,
    these are different flats — each known floor becomes its own sub-cluster
    and the None-floor rows form a separate group so they don't get
    arbitrarily attached to one of the floors.
    """
    by_floor: dict[int | None, list[Listing]] = defaultdict(list)
    for listing in cluster:
        by_floor[listing.floor].append(listing)

    known_floors = [f for f in by_floor if f is not None]
    if len(known_floors) <= 1:
        return [cluster]

    sub_clusters = [by_floor[f] for f in known_floors]
    none_rows = by_floor.get(None, [])
    if len(none_rows) >= 2:
        sub_clusters.append(none_rows)
    return sub_clusters


def _cluster_by_price(listings: list[Listing]) -> list[list[Listing]]:
    """Greedy single-pass clustering on the price-sorted list — extend the
    current cluster while the new row stays within ±tolerance of the pivot
    (the cluster's first price); start a new cluster otherwise."""
    sorted_listings = sorted(listings, key=lambda l: l.price_usd or 0.0)
    clusters: list[list[Listing]] = []
    current: list[Listing] = []
    pivot = 0.0
    for listing in sorted_listings:
        price = listing.price_usd or 0.0
        if not current or pivot == 0:
            current = [listing]
            pivot = price
            continue
        if abs(price - pivot) / pivot <= LOOSE_DEDUP_PRICE_TOLERANCE:
            current.append(listing)
        else:
            clusters.append(current)
            current = [listing]
            pivot = price
    if current:
        clusters.append(current)
    return clusters


def _merge_cluster(
    cluster: list[Listing], db: Session, dry_run: bool
) -> tuple[Listing, list[Listing]]:
    # Prefer active rows; then the cheapest ask (the panel surfaces the best
    # deal for the same flat); then most recently seen; then lowest id.
    cluster.sort(
        key=lambda l: (
            0 if l.status == "active" else 1,
            l.price_usd if l.price_usd is not None else float("inf"),
            -(l.seen_at.timestamp() if l.seen_at else 0.0),
            l.id,
        )
    )
    canonical, *extras = cluster
    urls = loads_json(canonical.source_urls, [])
    for extra in extras:
        urls = merge_source_urls(urls, loads_json(extra.source_urls, []))
    if not dry_run:
        # Carry over factual fields the canonical happens to be missing —
        # OLX cards routinely include ``этаж`` on one repost and omit it on
        # another, and the cheaper-ask pick that wins canonical is often the
        # one with the sparser title. Photos likewise: keep whatever's there.
        for field in ("floor", "total_floors"):
            if getattr(canonical, field) is None:
                for extra in extras:
                    value = getattr(extra, field)
                    if value is not None:
                        setattr(canonical, field, value)
                        break
        if not _has_photos_json(canonical.photos):
            for extra in extras:
                if _has_photos_json(extra.photos):
                    canonical.photos = extra.photos
                    break
        canonical.source_urls = dumps_json(urls)
        canonical.duplicate_count = max(1, len(urls))
        canonical.updated_at = datetime.utcnow()
        for extra in extras:
            db.delete(extra)
    return canonical, extras


def _has_photos_json(raw: str | None) -> bool:
    return bool(raw) and raw not in ("[]", "")
