"""One-time migration: local diskcache -> Supabase arbs_kv_cache_v1.

Usage:
    python scripts/migrate_diskcache_to_supabase.py [--dry-run] [--batch-size 10000]
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

import cloudpickle
import diskcache

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def discover_caches(cache_root: Path) -> list[tuple[str, Path]]:
    """Find all diskcache directories under cache_root."""
    caches = []
    if not cache_root.exists():
        return caches
    for d in sorted(cache_root.iterdir()):
        if d.is_dir() and (d / "cache.db").exists():
            caches.append((d.name, d))
        # FanoutCache has numbered subdirectories
        elif d.is_dir():
            subdirs = list(d.iterdir())
            if any((sd / "cache.db").exists() for sd in subdirs if sd.is_dir()):
                caches.append((d.name, d))
    return caches


def migrate_namespace(
    cache_dir: Path, cache_ns: str, *, batch_size: int = 10_000, dry_run: bool = False
) -> int:
    """Migrate a single diskcache namespace to Supabase."""
    from Caching.supabase_engine import get_engine
    from sqlalchemy import text

    engine = get_engine()
    if engine is None:
        logger.error("Supabase cache engine disabled or unavailable — cannot migrate.")
        return 0

    try:
        cache = diskcache.FanoutCache(str(cache_dir))
    except Exception:
        logger.warning("Could not open cache at %s", cache_dir, exc_info=True)
        return 0

    total = 0
    batch = []

    for key in cache:
        try:
            value = cache[key]
            payload = cloudpickle.dumps(value)
            cache_key = hashlib.sha256(cloudpickle.dumps(key)).hexdigest()
            batch.append({
                "ns": cache_ns,
                "key": cache_key,
                "repr": repr(key)[:500],
                "payload": payload,
                "serializer": "cloudpickle",
            })
        except Exception:
            logger.warning("Skipping key %r in %s", key, cache_ns, exc_info=True)
            continue

        if len(batch) >= batch_size:
            if not dry_run:
                _flush_batch(engine, batch)
            total += len(batch)
            logger.info("%s: %d records migrated so far", cache_ns, total)
            batch.clear()

    if batch and not dry_run:
        _flush_batch(engine, batch)
    total += len(batch)
    logger.info("%s: %d total records migrated", cache_ns, total)
    return total


def _flush_batch(engine, batch):
    from sqlalchemy import text

    with engine.begin() as conn:
        for row in batch:
            conn.execute(
                text("""
                    INSERT INTO arbs_kv_cache_v1
                        (cache_ns, cache_key, key_repr, payload, serializer, updated_at)
                    VALUES (:ns, :key, :repr, :payload, :serializer, NOW())
                    ON CONFLICT (cache_ns, cache_key) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        updated_at = NOW()
                """),
                row,
            )


def main():
    parser = argparse.ArgumentParser(description="Migrate diskcache to Supabase")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--cache-root", type=str, default=None)
    args = parser.parse_args()

    from Caching.DiskCacheMixin import DiskCacheMixin
    cache_root = Path(args.cache_root) if args.cache_root else DiskCacheMixin._user_cache_root() / "dump"

    caches = discover_caches(cache_root)
    logger.info("Found %d cache namespaces under %s", len(caches), cache_root)

    grand_total = 0
    for ns, path in caches:
        count = migrate_namespace(path, ns, batch_size=args.batch_size, dry_run=args.dry_run)
        grand_total += count

    logger.info("Migration complete: %d total records", grand_total)


if __name__ == "__main__":
    main()
