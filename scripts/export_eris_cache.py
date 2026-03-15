#!/usr/bin/env python
"""Export Eris diskcache raw CSV entries to Parquet CurveStore.

Usage:
    python -m scripts.export_eris_cache
    python -m scripts.export_eris_cache --dry-run
    python -m scripts.export_eris_cache --overwrite
    python -m scripts.export_eris_cache --source-variant ERIS_QL_BASIC

Reads every EOD_DiscountFactors_SOFR entry from the Eris raw diskcache,
parses the CSV, extracts (Date, DiscountFactor) pairs, and writes daily
Parquet files via CurveStore.
"""
from __future__ import annotations

import argparse
import datetime
import sys
import time
from io import BytesIO
from typing import Dict, Optional

import diskcache
import pandas as pd

from Caching.curve_store import CurveSnapshot, CurveStore
from Caching.DiskCacheMixin import DiskCacheMixin


def _open_eris_cache() -> diskcache.FanoutCache:
    path = DiskCacheMixin.default_cache_path("ErisFuturesFetcher-raw.fs")
    return diskcache.FanoutCache(directory=path, shards=8, size_limit=2**32)


def export(
    *,
    source_variant: str = "ERIS_RL_BASIC",
    curve_name: str = "USD-SOFR-1D",
    dry_run: bool = False,
    overwrite: bool = False,
    store: Optional[CurveStore] = None,
) -> dict:
    fc = _open_eris_cache()
    if store is None:
        store = CurveStore()

    print(f"CurveStore base dir: {store.base_dir}")
    print(f"Eris diskcache entries: {len(fc)}")

    t0 = time.perf_counter()
    groups: Dict[datetime.date, CurveSnapshot] = {}
    n_total = 0
    n_skipped = 0
    n_errors = 0

    try:
        import tqdm

        keys_iter = tqdm.tqdm(fc, desc="Scanning Eris diskcache", unit=" keys")
    except ImportError:
        keys_iter = fc

    for key in keys_iter:
        if not key.startswith("EOD_DiscountFactors_SOFR::"):
            n_skipped += 1
            continue

        try:
            payload = fc[key]
            content_bytes = payload["content"] if isinstance(payload, dict) else payload
            df = pd.read_csv(BytesIO(content_bytes), low_memory=False)

            trading_date = datetime.date.fromisoformat(key.split("::")[-1])
            groups[trading_date] = CurveSnapshot.from_eris_df(
                df,
                trading_date=trading_date,
                curve_name=curve_name,
                source_variant=source_variant,
            )
            n_total += 1
        except Exception as exc:
            n_errors += 1
            if n_errors <= 5:
                print(f"  WARN: failed to parse key={key}: {exc}", file=sys.stderr)

    t_scan = time.perf_counter() - t0
    print(f"\nScanned {n_total} Eris EOD curves in {t_scan:.1f}s")
    if n_errors:
        print(f"  {n_errors} keys failed to parse")
    if n_skipped:
        print(f"  {n_skipped} keys skipped (non-EOD_DiscountFactors)")

    if dry_run:
        for trading_date in sorted(groups):
            snap = groups[trading_date]
            print(f"  {trading_date}: {len(snap.node_dates)} nodes")
        print("\n[DRY RUN] No files written.")
        return {
            "curves_scanned": n_total,
            "errors": n_errors,
            "scan_time_s": t_scan,
        }

    t0 = time.perf_counter()
    n_written = 0
    n_skipped_existing = 0
    total_bytes = 0

    try:
        import tqdm

        dates_iter = tqdm.tqdm(sorted(groups), desc="Writing Parquet", unit=" days")
    except ImportError:
        dates_iter = sorted(groups)

    for trading_date in dates_iter:
        meta = store.write_day(
            curve_name,
            trading_date,
            [groups[trading_date]],
            overwrite=overwrite,
        )
        if meta is not None:
            n_written += 1
            total_bytes += meta["size"]
        else:
            n_skipped_existing += 1

    t_write = time.perf_counter() - t0
    print(
        f"\nWritten {n_written} day-files ({total_bytes / 1024:.1f} KB) in {t_write:.1f}s"
    )
    if n_skipped_existing:
        print(f"  {n_skipped_existing} days skipped (identical content)")

    return {
        "curves_scanned": n_total,
        "days_written": n_written,
        "days_skipped": n_skipped_existing,
        "total_bytes": total_bytes,
        "errors": n_errors,
        "scan_time_s": t_scan,
        "write_time_s": t_write,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Eris diskcache to Parquet CurveStore"
    )
    parser.add_argument(
        "--source-variant",
        default="ERIS_RL_BASIC",
        help="Source variant tag",
    )
    parser.add_argument("--curve-name", default="USD-SOFR-1D", help="Curve name")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()

    store = CurveStore(base_dir=args.base_dir) if args.base_dir else CurveStore()
    stats = export(
        source_variant=args.source_variant,
        curve_name=args.curve_name,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        store=store,
    )
    print(f"\nDone. Summary: {stats}")


if __name__ == "__main__":
    main()
