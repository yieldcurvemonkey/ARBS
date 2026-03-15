#!/usr/bin/env python
"""Export BARCHART_STIRF diskcache curve entries to Parquet CurveStore.

Usage:
    python -m scripts.export_curve_cache
    python -m scripts.export_curve_cache --curve-name USD-SOFR-1D-Q12STIRT
    python -m scripts.export_curve_cache --dry-run
    python -m scripts.export_curve_cache --overwrite

This reads every key from the diskcache FanoutCache, extracts node dates +
discount factors via json.loads() (NOT rl.from_json() — 0.02ms vs 1.6ms per
curve), groups by (curve_name, trading_date), and writes daily Parquet files.

The export is content-addressed: re-running skips days whose SHA256 hasn't changed.
"""
from __future__ import annotations

import argparse
import datetime
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import diskcache

from Caching.curve_store import CurveSnapshot, CurveStore
from Caching.DiskCacheMixin import DiskCacheMixin


def _open_curve_cache() -> diskcache.FanoutCache:
    """Open the BARCHART_STIRF curve diskcache."""
    path = DiskCacheMixin.default_cache_path("BARCHART_STIRF-RL_CURVE_CACHE")
    return diskcache.FanoutCache(directory=path, shards=8, size_limit=2**32)


def export(
    *,
    curve_name_filter: Optional[str] = None,
    dry_run: bool = False,
    overwrite: bool = False,
    store: Optional[CurveStore] = None,
) -> dict:
    """Run the full export.

    Returns summary stats dict.
    """
    fc = _open_curve_cache()
    if store is None:
        store = CurveStore()

    print(f"CurveStore base dir: {store.base_dir}")
    print(f"Diskcache entries:   {len(fc)}")

    # Phase 1: iterate cache and build snapshots, grouped by (curve_name, trading_date)
    t0 = time.perf_counter()
    groups: Dict[tuple[str, datetime.date], List[CurveSnapshot]] = defaultdict(list)
    n_total = 0
    n_skipped = 0
    n_errors = 0

    try:
        import tqdm

        keys_iter = tqdm.tqdm(fc, desc="Scanning diskcache", unit=" keys")
    except ImportError:
        keys_iter = fc

    for key in keys_iter:
        # Skip non-curve keys (e.g., BUNDLE_ keys)
        if not key.startswith("v"):
            continue
        if "BUNDLE" in key:
            continue
        if curve_name_filter and curve_name_filter not in key:
            n_skipped += 1
            continue

        try:
            payload = fc[key]
            snap = CurveSnapshot.from_diskcache_payload(cache_key=key, payload=payload)
            groups[(snap.curve_name, snap.trading_date)].append(snap)
            n_total += 1
        except Exception as e:
            n_errors += 1
            if n_errors <= 5:
                print(f"  WARN: failed to parse key={key}: {e}", file=sys.stderr)

    t_scan = time.perf_counter() - t0
    print(f"\nScanned {n_total} curves into {len(groups)} (curve, day) groups in {t_scan:.1f}s")
    if n_errors:
        print(f"  {n_errors} keys failed to parse")
    if n_skipped:
        print(f"  {n_skipped} keys skipped (filter)")

    if dry_run:
        # Print summary without writing
        for (cn, td), snaps in sorted(groups.items()):
            print(f"  {cn} / {td}: {len(snaps)} snapshots")
        print("\n[DRY RUN] No files written.")
        return {
            "curves_scanned": n_total,
            "groups": len(groups),
            "errors": n_errors,
            "scan_time_s": t_scan,
        }

    # Phase 2: write Parquet files
    t0 = time.perf_counter()
    n_written = 0
    n_skipped_existing = 0
    total_bytes = 0

    try:
        import tqdm

        groups_iter = tqdm.tqdm(
            sorted(groups.items()),
            desc="Writing Parquet",
            unit=" days",
        )
    except ImportError:
        groups_iter = sorted(groups.items())

    for (curve_name, trading_date), snaps in groups_iter:
        # Sort snapshots by timestamp
        snaps.sort(key=lambda s: s.timestamp_utc)

        meta = store.write_day(
            curve_name,
            trading_date,
            snaps,
            overwrite=overwrite,
        )
        if meta is not None:
            n_written += 1
            total_bytes += meta["size"]
        else:
            n_skipped_existing += 1

    t_write = time.perf_counter() - t0
    print(f"\nWritten {n_written} day-files ({total_bytes / 1024:.1f} KB) in {t_write:.1f}s")
    if n_skipped_existing:
        print(f"  {n_skipped_existing} days skipped (identical content already exists)")

    return {
        "curves_scanned": n_total,
        "groups": len(groups),
        "days_written": n_written,
        "days_skipped": n_skipped_existing,
        "total_bytes": total_bytes,
        "errors": n_errors,
        "scan_time_s": t_scan,
        "write_time_s": t_write,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export diskcache curves to Parquet CurveStore")
    parser.add_argument("--curve-name", default=None, help="Only export curves matching this name")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, don't write files")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Parquet files")
    parser.add_argument("--base-dir", default=None, help="CurveStore base directory (default: auto)")
    args = parser.parse_args()

    store = CurveStore(base_dir=args.base_dir) if args.base_dir else CurveStore()

    stats = export(
        curve_name_filter=args.curve_name,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        store=store,
    )
    print(f"\nDone. Summary: {stats}")


if __name__ == "__main__":
    main()
