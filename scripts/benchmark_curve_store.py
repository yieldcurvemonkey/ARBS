#!/usr/bin/env python
"""Benchmark CurveStore read/write/reconstruct performance.

Usage:
    python -m scripts.benchmark_curve_store
    python -m scripts.benchmark_curve_store --curve-name USD-SOFR-1D-Q12STIRT

Run this AFTER running export_curve_cache.py to populate the Parquet store.
"""
from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path
from typing import Optional

from Caching.curve_store import CurveStore


def _fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f}ms"


def _fmt_rate(seconds: float, count: int) -> str:
    if count == 0:
        return "N/A"
    per_item = seconds / count * 1000
    return f"{per_item:.3f}ms/item"


def benchmark(
    curve_name: str = "USD-SOFR-1D-Q12STIRT",
    store: Optional[CurveStore] = None,
) -> None:
    if store is None:
        store = CurveStore()

    print(f"CurveStore base dir: {store.base_dir}")
    print(f"Curve: {curve_name}")
    print()

    # Check available dates
    dates = store.available_dates(curve_name)
    if not dates:
        print("ERROR: No data found. Run export_curve_cache.py first.")
        return

    print(f"Available dates: {len(dates)} ({dates[0]} to {dates[-1]})")
    print()

    # ── Benchmark 1: Single day read ──
    # Pick a date with the most data (likely latest)
    test_date = dates[-1]
    t0 = time.perf_counter()
    df_day = store.read_raw_nodes(curve_name, start=test_date, end=test_date)
    t1 = time.perf_counter()
    print(f"1. Single day read ({test_date}, {len(df_day)} rows): {_fmt_ms(t1-t0)}  target: <10ms")

    # ── Benchmark 2: Single month read ──
    if len(dates) >= 20:
        month_end = dates[-1]
        month_start = dates[-min(22, len(dates))]
        t0 = time.perf_counter()
        df_month = store.read_raw_nodes(curve_name, start=month_start, end=month_end)
        t1 = time.perf_counter()
        print(f"2. ~Month read ({month_start} to {month_end}, {len(df_month)} rows): {_fmt_ms(t1-t0)}  target: <100ms")
    else:
        print(f"2. ~Month read: SKIPPED (only {len(dates)} dates)")

    # ── Benchmark 3: Full range read ──
    t0 = time.perf_counter()
    df_all = store.read_raw_nodes(curve_name, start=dates[0], end=dates[-1])
    t1 = time.perf_counter()
    full_time = t1 - t0
    print(f"3. Full range read ({dates[0]} to {dates[-1]}, {len(df_all)} rows): {_fmt_ms(full_time)}  target: <5s for 725K rows")

    # ── Benchmark 4: Single curve reconstruction ──
    if len(df_day) > 0:
        row = df_day.iloc[0].to_dict()
        # Warm up
        _ = store.reconstruct_curve(row)
        # Benchmark
        t0 = time.perf_counter()
        N_SINGLE = 100
        for _ in range(N_SINGLE):
            store.reconstruct_curve(row)
        t1 = time.perf_counter()
        print(f"4. Single curve reconstruction (avg of {N_SINGLE}): {_fmt_rate(t1-t0, N_SINGLE)}  expect: ~1.6ms")

    # ── Benchmark 5: Day batch reconstruction ──
    if len(df_day) > 0:
        for workers in [1, 4, 8]:
            t0 = time.perf_counter()
            curves = store.reconstruct_curves_batch(df_day, max_workers=workers)
            t1 = time.perf_counter()
            print(f"5. Day batch ({len(df_day)} curves, {workers}w): {_fmt_ms(t1-t0)}  {_fmt_rate(t1-t0, len(df_day))}  target: <200ms")

    # ── Benchmark 6: Write performance ──
    # Re-export a single day to measure write speed
    from Caching.curve_store import CurveSnapshot
    import diskcache
    from Caching.DiskCacheMixin import DiskCacheMixin

    cache_path = DiskCacheMixin.default_cache_path("BARCHART_STIRF-RL_CURVE_CACHE")
    fc = diskcache.FanoutCache(directory=cache_path, shards=8, size_limit=2**32)

    snaps = []
    for k in fc:
        if curve_name in k and "BUNDLE" not in k:
            try:
                snap = CurveSnapshot.from_diskcache_payload(cache_key=k, payload=fc[k])
                if snap.trading_date == test_date:
                    snaps.append(snap)
            except Exception:
                continue
            if len(snaps) >= 500:
                break

    if snaps:
        import tempfile, shutil

        tmpdir = Path(tempfile.mkdtemp())
        tmp_store = CurveStore(base_dir=tmpdir)
        t0 = time.perf_counter()
        tmp_store.write_day(curve_name, test_date, snaps, overwrite=True)
        t1 = time.perf_counter()
        print(f"6. Write day ({len(snaps)} snapshots): {_fmt_ms(t1-t0)}  target: <50ms")
        shutil.rmtree(tmpdir)

    # ── Benchmark 7: File sizes ──
    asset_dir = store._raw_dir / f"asset={curve_name.replace('-', '_').replace(' ', '_')}"
    if not asset_dir.exists():
        # Try with different sanitization
        from Caching.curve_store import _sanitize
        asset_dir = store._raw_dir / f"asset={_sanitize(curve_name)}"

    if asset_dir.exists():
        total_size = sum(f.stat().st_size for f in asset_dir.rglob("*.parquet"))
        n_files = sum(1 for _ in asset_dir.rglob("*.parquet"))
        print(f"\n7. Storage: {n_files} files, {total_size / 1024:.1f} KB total")
        if len(df_all) > 0:
            raw_bytes = len(df_all) * 21 * 12  # ~21 nodes * (4 byte date + 8 byte float)
            print(f"   Compression ratio: {total_size / max(raw_bytes, 1):.2f}x")
            print(f"   Bytes/snapshot: {total_size / len(df_all):.0f}")

    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark CurveStore performance")
    parser.add_argument(
        "--curve-name",
        default="USD-SOFR-1D-Q12STIRT",
        help="Curve name to benchmark",
    )
    parser.add_argument("--base-dir", default=None, help="CurveStore base directory")
    args = parser.parse_args()

    store = CurveStore(base_dir=args.base_dir) if args.base_dir else CurveStore()
    benchmark(curve_name=args.curve_name, store=store)


if __name__ == "__main__":
    main()
