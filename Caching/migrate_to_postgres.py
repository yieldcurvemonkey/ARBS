"""
Migrate warm local diskcache to Postgres L2.

Scans all FanoutCache directories under the default cache root, iterates their
entries, pickles the values, and bulk-upserts them into the arbs_kv_cache_v1
table.  Idempotent: uses ON CONFLICT … DO UPDATE so re-running is safe.

Usage
-----
    python -m Caching.migrate_to_postgres                  # migrate all caches
    python -m Caching.migrate_to_postgres --dry-run         # count entries only
    python -m Caching.migrate_to_postgres --dir /path       # migrate specific dir
    python -m Caching.migrate_to_postgres --skip-vacuum     # skip post-migration VACUUM

After bulk upserts complete, the script automatically runs
``VACUUM (VERBOSE, ANALYZE)`` on the cache table to reclaim dead tuples
and refresh planner statistics.  Use ``--skip-vacuum`` to disable this
(not recommended — autovacuum will eventually clean up, but with more
bloat in the interim).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import diskcache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

_NS_RX = re.compile(r"[^\w.\-]")


def _namespace_from_path(path: str) -> str:
    stem = Path(path).name
    return _NS_RX.sub("_", stem)


def _discover_cache_dirs(root: Path) -> list[Path]:
    """Find all diskcache directories under root (contain cache.db-* shards)."""
    dirs = []
    if not root.exists():
        return dirs
    for child in root.iterdir():
        if child.is_dir():
            # diskcache FanoutCache creates numbered shard subdirs
            shards = [s for s in child.iterdir() if s.is_dir() and s.name.isdigit()]
            if shards:
                dirs.append(child)
    return sorted(dirs)


def _default_cache_root() -> Path:
    try:
        from platformdirs import user_cache_dir

        return Path(user_cache_dir(appname="ARBS", appauthor=False)) / "diskcache" / "dump"
    except Exception:
        if os.name == "nt":
            return (
                Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "diskcache" / "dump"
            )
        return Path.home() / ".cache" / "arbs" / "diskcache" / "dump"


def migrate_directory(
    cache_dir: Path,
    *,
    batch_size: int = 500,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Migrate a single FanoutCache directory to Postgres.

    Returns dict with keys: namespace, total_keys, migrated, skipped, errors.
    """
    ns = _namespace_from_path(str(cache_dir))
    logger.info("Opening FanoutCache: %s  →  namespace: %s", cache_dir, ns)

    fc = diskcache.FanoutCache(directory=str(cache_dir), shards=8)
    total = len(fc)
    logger.info("  %d entries found", total)

    if dry_run:
        fc.close()
        return {"namespace": ns, "total_keys": total, "migrated": 0, "skipped": 0, "errors": 0}

    from Caching.pg_backend import PostgresCacheBackend

    backend = PostgresCacheBackend(namespace=ns)

    migrated = 0
    skipped = 0
    errors = 0
    batch: list[tuple[str, object]] = []

    for key in fc:
        try:
            value = fc[key]
        except Exception as e:
            logger.warning("  Error reading key=%s: %s", key, e)
            errors += 1
            continue

        batch.append((str(key), value))

        if len(batch) >= batch_size:
            try:
                backend.bulk_put(batch, batch_size=batch_size)
                migrated += len(batch)
            except Exception as e:
                logger.error("  Batch write failed: %s", e)
                errors += len(batch)
            batch.clear()
            if migrated % 2000 == 0:
                logger.info("  ... %d / %d migrated", migrated, total)

    # flush remaining
    if batch:
        try:
            backend.bulk_put(batch, batch_size=batch_size)
            migrated += len(batch)
        except Exception as e:
            logger.error("  Final batch write failed: %s", e)
            errors += len(batch)

    fc.close()
    logger.info(
        "  Done: %d migrated, %d skipped, %d errors (of %d total)",
        migrated,
        skipped,
        errors,
        total,
    )
    return {
        "namespace": ns,
        "total_keys": total,
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
    }


def _post_migration_vacuum(engine: "Engine") -> None:
    """
    Run VACUUM (ANALYZE) on the cache table after bulk migration.

    Bulk upserts generate dead tuples for every existing row that was
    overwritten.  A manual VACUUM reclaims that space immediately rather
    than waiting for autovacuum's next pass, and ANALYZE refreshes planner
    statistics so our indexes are used optimally.

    NOTE: VACUUM cannot run inside a transaction block, so we use the
    raw psycopg2 connection with autocommit=True.
    """
    from Caching.pg_backend import TABLE

    logger.info("Running VACUUM (ANALYZE) on %s …", TABLE)
    t0 = time.time()
    raw_conn = engine.raw_connection()
    try:
        raw_conn.autocommit = True
        cur = raw_conn.cursor()
        cur.execute(f"VACUUM (VERBOSE, ANALYZE) {TABLE}")
        cur.close()
    except Exception:
        logger.warning("VACUUM (ANALYZE) failed — autovacuum will handle it eventually", exc_info=True)
    finally:
        raw_conn.close()
    logger.info("VACUUM (ANALYZE) completed in %.1fs", time.time() - t0)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Migrate warm diskcache to Postgres L2")
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Migrate a specific cache directory instead of auto-discovering",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help="Override the cache root directory for auto-discovery",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true", help="Count entries without writing")
    parser.add_argument(
        "--skip-vacuum",
        action="store_true",
        help="Skip post-migration VACUUM ANALYZE (not recommended)",
    )
    args = parser.parse_args(argv)

    if args.dir:
        dirs = [Path(args.dir)]
    else:
        root = Path(args.root) if args.root else _default_cache_root()
        logger.info("Scanning cache root: %s", root)
        dirs = _discover_cache_dirs(root)
        if not dirs:
            logger.info("No FanoutCache directories found under %s", root)
            return
        logger.info("Found %d cache directories", len(dirs))

    t0 = time.time()
    results = []
    for d in dirs:
        result = migrate_directory(d, batch_size=args.batch_size, dry_run=args.dry_run)
        results.append(result)

    elapsed = time.time() - t0
    total_keys = sum(r["total_keys"] for r in results)
    total_migrated = sum(r["migrated"] for r in results)
    total_errors = sum(r["errors"] for r in results)

    logger.info("=" * 60)
    logger.info("Migration complete in %.1fs", elapsed)
    logger.info("  Directories: %d", len(results))
    logger.info("  Total keys:  %d", total_keys)
    logger.info("  Migrated:    %d", total_migrated)
    logger.info("  Errors:      %d", total_errors)
    logger.info("=" * 60)

    for r in results:
        logger.info("  %-40s  keys=%d  migrated=%d  errors=%d", r["namespace"], r["total_keys"], r["migrated"], r["errors"])

    # Post-migration: reclaim dead tuples and refresh planner stats
    if not args.dry_run and not args.skip_vacuum and total_migrated > 0:
        from Caching.pg_backend import get_engine

        _post_migration_vacuum(get_engine())


if __name__ == "__main__":
    main()
