#!/usr/bin/env python
"""Export BARCHART_STIRF diskcache curve entries to Parquet CurveStore.

Usage:
    python -m scripts.export_curve_cache
    python -m scripts.export_curve_cache --curve-name USD-SOFR-1D-Q12STIRT
    python -m scripts.export_curve_cache --dry-run
    python -m scripts.export_curve_cache --overwrite
    python -m scripts.export_curve_cache --bundles-only

This reads every key from the diskcache FanoutCache, extracts node dates +
discount factors via json.loads() (NOT rl.from_json() — 0.02ms vs 1.6ms per
curve), groups by (curve_name, trading_date), and writes daily Parquet files.

Handles two entry types:
  - Individual entries: v{schema}_{curve_name}_{ts}_{cfg_hash}
  - Bundle entries:     v{schema}_BUNDLE_{curve_name}_{date}_{cfg_hash}
    Each bundle contains nodes_by_ts: {ts_iso: {node_date_iso: discount_factor}}
    representing an entire day of intraday curves.

The export is content-addressed: re-running skips days whose SHA256 hasn't changed.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import diskcache
import pandas as pd
import pytz

from Caching.curve_store import CurveSnapshot, CurveStore
from Caching.DiskCacheMixin import DiskCacheMixin

_UTC = pytz.UTC
_CHI = pytz.timezone("America/Chicago")

# Regex for bundle keys: v{schema}_BUNDLE_{curve_name}_{YYYYMMDD}_{cfg_hash}
_BUNDLE_KEY_RX = re.compile(
    r"^v(\d+)_BUNDLE_(.+?)_(\d{8})_([a-f0-9]{16})$"
)


def _open_curve_cache() -> diskcache.FanoutCache:
    """Open the BARCHART_STIRF curve diskcache."""
    path = DiskCacheMixin.default_cache_path("BARCHART_STIRF-RL_CURVE_CACHE")
    return diskcache.FanoutCache(directory=path, shards=8, size_limit=2**32)


def _parse_bundle_key(key: str):
    """Parse a bundle key. Returns (curve_name, date, cfg_hash) or None."""
    m = _BUNDLE_KEY_RX.match(key)
    if m:
        curve_name = m.group(2)
        date_str = m.group(3)
        cfg_hash = m.group(4)
        trading_date = datetime.date(
            int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8])
        )
        return curve_name, trading_date, cfg_hash
    return None


def _snapshots_from_bundle(
    key: str,
    payload: dict,
) -> List[CurveSnapshot]:
    """Extract CurveSnapshot objects from a bundle payload.

    Bundle payload format:
        {
            "schema": 1,
            "curve_name": "USD-SOFR-1D-Q12STIRT",
            "date": "2026-03-13",
            "nodes_by_ts": {
                "2026-03-13T12:00:00+00:00": {
                    "2026-03-13T00:00:00": 1.0,
                    "2026-06-18T00:00:00": 0.987654,
                    ...
                },
                ...
            }
        }
    """
    parsed = _parse_bundle_key(key)
    if parsed is None:
        raise ValueError(f"Cannot parse bundle key: {key}")

    key_curve_name, key_trading_date, cfg_hash = parsed
    curve_name = payload.get("curve_name", key_curve_name)
    date_str = payload.get("date", "")
    if date_str:
        trading_date = datetime.date.fromisoformat(date_str)
    else:
        trading_date = key_trading_date

    nodes_by_ts = payload.get("nodes_by_ts", {})
    if not nodes_by_ts:
        return []

    snapshots: List[CurveSnapshot] = []
    for ts_iso, node_dict in nodes_by_ts.items():
        # Parse timestamp
        ts_utc = pd.Timestamp(ts_iso)
        if ts_utc.tzinfo is None:
            ts_utc = _UTC.localize(ts_utc.to_pydatetime())
        else:
            ts_utc = ts_utc.to_pydatetime().astimezone(_UTC)
        ts_local = ts_utc.astimezone(_CHI)

        # Parse nodes: {node_date_iso: discount_factor}
        # Node keys are pd.Timestamp(...).isoformat() — e.g., "2026-03-13T00:00:00"
        sorted_node_keys = sorted(node_dict.keys())
        node_dates = []
        discount_factors = []
        for nk in sorted_node_keys:
            try:
                nd = pd.Timestamp(nk).date()
            except Exception:
                continue
            node_dates.append(nd)
            discount_factors.append(float(node_dict[nk]))

        if not node_dates:
            continue

        # Compute session metadata
        from Caching.curve_store import _compute_trading_date, _compute_session_minute

        snap = CurveSnapshot(
            timestamp_utc=ts_utc,
            timestamp_local=ts_local,
            trading_date=trading_date,
            session_minute=_compute_session_minute(ts_local),
            curve_name=curve_name,
            cfg_hash=cfg_hash,
            reference_key=curve_name,  # Best available from bundle
            interpolation="log_linear",  # Default; bundles don't store this
            source_variant="BARCHART_STIRF",
            node_dates=node_dates,
            discount_factors=discount_factors,
        )
        snapshots.append(snap)

    return snapshots


def export(
    *,
    curve_name_filter: Optional[str] = None,
    dry_run: bool = False,
    overwrite: bool = False,
    bundles_only: bool = False,
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
    n_individual = 0
    n_bundle_keys = 0
    n_bundle_curves = 0
    n_skipped = 0
    n_errors = 0

    try:
        import tqdm

        keys_iter = tqdm.tqdm(fc, desc="Scanning diskcache", unit=" keys")
    except ImportError:
        keys_iter = fc

    for key in keys_iter:
        if not key.startswith("v"):
            continue

        is_bundle = "BUNDLE" in key

        if bundles_only and not is_bundle:
            continue

        if curve_name_filter and curve_name_filter not in key:
            n_skipped += 1
            continue

        try:
            payload = fc[key]

            if is_bundle:
                # Parse bundle entry: contains nodes_by_ts with all intraday curves
                if not isinstance(payload, dict):
                    n_errors += 1
                    continue
                snaps = _snapshots_from_bundle(key, payload)
                n_bundle_keys += 1
                n_bundle_curves += len(snaps)
                for snap in snaps:
                    groups[(snap.curve_name, snap.trading_date)].append(snap)
            else:
                # Parse individual entry
                snap = CurveSnapshot.from_diskcache_payload(cache_key=key, payload=payload)
                groups[(snap.curve_name, snap.trading_date)].append(snap)
                n_individual += 1
        except Exception as e:
            n_errors += 1
            if n_errors <= 5:
                print(f"  WARN: failed to parse key={key}: {e}", file=sys.stderr)

    n_total = n_individual + n_bundle_curves
    t_scan = time.perf_counter() - t0
    print(f"\nScanned {n_total} curves into {len(groups)} (curve, day) groups in {t_scan:.1f}s")
    print(f"  {n_individual} from individual entries")
    print(f"  {n_bundle_curves} from {n_bundle_keys} bundle entries")
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
            "individual_entries": n_individual,
            "bundle_keys": n_bundle_keys,
            "bundle_curves": n_bundle_curves,
            "groups": len(groups),
            "errors": n_errors,
            "scan_time_s": t_scan,
        }

    # Phase 2: deduplicate by timestamp within each group, then write Parquet
    t0 = time.perf_counter()
    n_written = 0
    n_skipped_existing = 0
    n_deduped = 0
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
        # Deduplicate: if both individual and bundle entries exist for the same
        # timestamp, prefer the individual entry (it has interpolation metadata).
        seen_ts: dict[datetime.datetime, CurveSnapshot] = {}
        for snap in snaps:
            existing = seen_ts.get(snap.timestamp_utc)
            if existing is None:
                seen_ts[snap.timestamp_utc] = snap
            elif snap.interpolation != "log_linear" and existing.interpolation == "log_linear":
                # Prefer the one with actual interpolation info
                seen_ts[snap.timestamp_utc] = snap
                n_deduped += 1
            else:
                n_deduped += 1

        deduped_snaps = sorted(seen_ts.values(), key=lambda s: s.timestamp_utc)

        meta = store.write_day(
            curve_name,
            trading_date,
            deduped_snaps,
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
    if n_deduped:
        print(f"  {n_deduped} duplicate timestamps deduplicated")

    return {
        "curves_scanned": n_total,
        "individual_entries": n_individual,
        "bundle_keys": n_bundle_keys,
        "bundle_curves": n_bundle_curves,
        "groups": len(groups),
        "days_written": n_written,
        "days_skipped": n_skipped_existing,
        "deduped": n_deduped,
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
    parser.add_argument("--bundles-only", action="store_true", help="Only export bundle entries (skip individual)")
    parser.add_argument("--base-dir", default=None, help="CurveStore base directory (default: auto)")
    args = parser.parse_args()

    store = CurveStore(base_dir=args.base_dir) if args.base_dir else CurveStore()

    stats = export(
        curve_name_filter=args.curve_name,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        bundles_only=args.bundles_only,
        store=store,
    )
    print(f"\nDone. Summary: {stats}")


if __name__ == "__main__":
    main()
