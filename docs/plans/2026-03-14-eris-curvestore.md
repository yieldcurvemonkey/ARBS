# Eris CurveStore Implementation Plan

**Goal:** Extend the existing Parquet-backed `CurveStore` to support Eris discount factor curves with both rateslib and QuantLib reconstruction, then wire a Tier 0 fast path into `IRSwapsMDP.bulk_get_data()` for the `ERIS_EOD_LIVE-RL_BASIC` source.

**Architecture:** Add a `source_variant` column to the existing raw Parquet schema to distinguish curve provenance (e.g., `RL_BASIC`, `QL_BASIC`, `QL_BASIC-NOJUMPS`). Add `CurveSnapshot.from_eris_df()` factory and `CurveStore.reconstruct_ql_curve()` alongside the existing `reconstruct_curve()` (rateslib). Wire Tier 0 Parquet fast path into `bulk_get_data()` for `ERIS_EOD_LIVE-RL_BASIC`. Add `scripts/export_eris_cache.py` for one-time migration from the diskcache raw CSV bytes to Parquet.

**Tech Stack:** PyArrow, DuckDB, rateslib, QuantLib-Python, diskcache

---

## Task 1: Add `source_variant` column to CurveStore raw schema

**Files:**
- Modify: `Caching/curve_store.py`

**Step 1: Add `source_variant` field to `CurveSnapshot` dataclass**

Add a new field after `interpolation`:
```python
source_variant: str = ""  # e.g. "BARCHART_STIRF", "ERIS_RL_BASIC", "ERIS_QL_BASIC", "ERIS_QL_BASIC_NOJUMPS"
```

**Step 2: Add `source_variant` to `_RAW_SCHEMA`**

Insert after the `interpolation` field:
```python
pa.field("source_variant", pa.dictionary(pa.int8(), pa.utf8())),
```

**Step 3: Update `_snapshots_to_arrow_table` to include `source_variant`**

Add a `svar` list, append `s.source_variant` per snapshot, dictionary-encode it, and include in the arrays list (position must match schema order).

**Step 4: Default `source_variant=""` in existing factory methods**

In `from_diskcache_payload()` and `from_rl_curve()`, set `source_variant="BARCHART_STIRF"` so existing STIRF exports get tagged.

**Step 5: Verify backward compatibility**

Existing Parquet files lack `source_variant`. Confirm that `read_raw_day()` and `read_raw_nodes()` still work — DuckDB/PyArrow will return `null` for the missing column. No migration needed; new writes will include it.


---

## Task 2: Add `CurveSnapshot.from_eris_df()` factory

**Files:**
- Modify: `Caching/curve_store.py`

**Step 1: Implement `from_eris_df` classmethod**

This factory builds a `CurveSnapshot` from an Eris discount factor DataFrame (columns: `Date`, `DiscountFactor`) plus metadata. Eris EOD has one snapshot per day, so `timestamp_utc` is set to 15:00 ET (20:00 UTC) on the trading date.

```python
@classmethod
def from_eris_df(
    cls,
    df: "pd.DataFrame",
    *,
    trading_date: datetime.date,
    curve_name: str = "USD-SOFR-1D",
    source_variant: str = "ERIS_RL_BASIC",
    interpolation: str = "log_linear",
    timestamp_utc: Optional[datetime.datetime] = None,
) -> "CurveSnapshot":
    """Build a snapshot from an Eris discount factor CSV DataFrame.

    The DataFrame must have 'Date' and 'DiscountFactor' columns.
    """
    import pandas as pd_local

    df = df.copy()
    df["Date"] = pd_local.to_datetime(df["Date"], errors="coerce")
    df["DiscountFactor"] = pd_local.to_numeric(df["DiscountFactor"], errors="coerce")
    df = df.dropna(subset=["Date", "DiscountFactor"]).sort_values("Date")

    node_dates = [d.date() for d in df["Date"]]
    discount_factors = df["DiscountFactor"].tolist()

    # Default EOD timestamp: 15:00 ET (market close)
    if timestamp_utc is None:
        _ET = pytz.timezone("America/New_York")
        ts_local_et = _ET.localize(
            datetime.datetime(trading_date.year, trading_date.month, trading_date.day, 15, 0)
        )
        timestamp_utc = ts_local_et.astimezone(_UTC)

    ts_local = timestamp_utc.astimezone(_CHI)

    return cls(
        timestamp_utc=timestamp_utc,
        timestamp_local=ts_local,
        trading_date=trading_date,
        session_minute=_compute_session_minute(ts_local),
        curve_name=curve_name,
        cfg_hash="",
        reference_key=curve_name,
        interpolation=interpolation,
        node_dates=node_dates,
        discount_factors=discount_factors,
        source_variant=source_variant,
    )
```


## Task 3: Add `reconstruct_ql_curve()` to `CurveStore`

**Files:**
- Modify: `Caching/curve_store.py`

**Step 1: Add `reconstruct_ql_curve` static method**

This reconstructs a `ql.DiscountCurve` from a raw store row (same node data as rateslib, different reconstruction).

```python
@staticmethod
def reconstruct_ql_curve(
    row: dict,
    *,
    ql_dc=None,
    ql_cal=None,
    interpolation_algo: str = "df_log_linear",
    enable_extrapolation: bool = True,
) -> Any:
    """Reconstruct a QuantLib DiscountCurve from a raw store row."""
    import pandas as pd_local

    from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import (
        build_ql_discount_curve,
    )

    if ql_dc is None:
        import QuantLib as ql
        ql_dc = ql.Actual360()
    if ql_cal is None:
        import QuantLib as ql
        ql_cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

    node_dates_raw = row["node_dates"]
    dfs_raw = row["discount_factors"]

    dates = [_to_date(d) for d in node_dates_raw]
    datetime_series = pd_local.Series([
        datetime.datetime(d.year, d.month, d.day) for d in dates
    ])
    df_series = pd_local.Series([float(v) for v in dfs_raw])

    ql_curve = build_ql_discount_curve(
        datetime_series=datetime_series,
        discount_factor_series=df_series,
        ql_dc=ql_dc,
        ql_cal=ql_cal,
        interpolation_algo=interpolation_algo,
    )
    if enable_extrapolation:
        ql_curve.enableExtrapolation()

    return ql_curve
```

**Step 2: Add `reconstruct_ql_curves_batch` classmethod**

```python
@classmethod
def reconstruct_ql_curves_batch(
    cls,
    df: "pd.DataFrame",
    *,
    ql_dc=None,
    ql_cal=None,
    interpolation_algo: str = "df_log_linear",
    enable_extrapolation: bool = True,
) -> Dict[datetime.date, Any]:
    """Batch reconstruct QL DiscountCurves. Returns {trading_date: ql.DiscountCurve}."""
    if df.empty:
        return {}

    rows = df.to_dict("records")
    result: Dict[datetime.date, Any] = {}

    for r in rows:
        td = r.get("trading_date")
        if td is None:
            continue
        td = _to_date(td)
        ql_curve = cls.reconstruct_ql_curve(
            r,
            ql_dc=ql_dc,
            ql_cal=ql_cal,
            interpolation_algo=interpolation_algo,
            enable_extrapolation=enable_extrapolation,
        )
        result[td] = ql_curve

    return result
```



## Task 4: Write `scripts/export_eris_cache.py` migration script

**Files:**
- Create: `scripts/export_eris_cache.py`

**Step 1: Implement the migration script**

This reads every entry from the `eris_raw` diskcache (keyed as `EOD_DiscountFactors_SOFR::{date}`), parses the CSV bytes into a DataFrame, builds a `CurveSnapshot.from_eris_df()`, and writes to CurveStore.

```python
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
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

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
            content_bytes = payload["content"]
            df = pd.read_csv(BytesIO(content_bytes), low_memory=False)

            # Extract date from key: "EOD_DiscountFactors_SOFR::2024-01-15"
            date_str = key.split("::")[-1]
            trading_date = datetime.date.fromisoformat(date_str)

            snap = CurveSnapshot.from_eris_df(
                df,
                trading_date=trading_date,
                curve_name=curve_name,
                source_variant=source_variant,
            )
            groups[trading_date] = snap
            n_total += 1
        except Exception as e:
            n_errors += 1
            if n_errors <= 5:
                print(f"  WARN: failed to parse key={key}: {e}", file=sys.stderr)

    t_scan = time.perf_counter() - t0
    print(f"\nScanned {n_total} Eris EOD curves in {t_scan:.1f}s")
    if n_errors:
        print(f"  {n_errors} keys failed to parse")
    if n_skipped:
        print(f"  {n_skipped} keys skipped (non-EOD_DiscountFactors)")

    if dry_run:
        for td in sorted(groups):
            snap = groups[td]
            print(f"  {td}: {len(snap.node_dates)} nodes")
        print("\n[DRY RUN] No files written.")
        return {"curves_scanned": n_total, "errors": n_errors, "scan_time_s": t_scan}

    # Write
    t0 = time.perf_counter()
    n_written = 0
    n_skipped_existing = 0
    total_bytes = 0

    try:
        import tqdm
        dates_iter = tqdm.tqdm(sorted(groups.keys()), desc="Writing Parquet", unit=" days")
    except ImportError:
        dates_iter = sorted(groups.keys())

    for td in dates_iter:
        snap = groups[td]
        meta = store.write_day(curve_name, td, [snap], overwrite=overwrite)
        if meta is not None:
            n_written += 1
            total_bytes += meta["size"]
        else:
            n_skipped_existing += 1

    t_write = time.perf_counter() - t0
    print(f"\nWritten {n_written} day-files ({total_bytes / 1024:.1f} KB) in {t_write:.1f}s")
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


def main():
    parser = argparse.ArgumentParser(description="Export Eris diskcache to Parquet CurveStore")
    parser.add_argument("--source-variant", default="ERIS_RL_BASIC", help="Source variant tag")
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
```


---

## Task 5: Wire Tier 0 fast path into `bulk_get_data()` for `ERIS_EOD_LIVE-RL_BASIC`

**Files:**
- Modify: `MDP/IRSwaps/IRSwapsMDP.py` (around line 1045, the `ERIS_EOD_LIVE-RL_BASIC` branch of `bulk_get_data`)

**Step 1: Add Tier 0 Parquet fast path before diskcache**

Insert before the existing `if past_dates:` block (line 1064). The pattern mirrors the BARCHART_STIRF Tier 0 block but is simpler since Eris is EOD (one snapshot per date, keyed by `trading_date` not `timestamp_utc`).

```python
elif self.source.upper() in ["ERIS_EOD_LIVE-RL_BASIC", "ERIS_EOD_LIVE_RL_BASIC"]:
    from rateslib import from_json

    from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

    def _to_date(x):
        if x == "live":
            return datetime.date.today()
        if isinstance(x, datetime.datetime):
            return x.date()
        return x

    bdates: List[datetime.date] = [_to_date(t) for t in timestamps]

    today = datetime.date.today()
    past_dates = [d for d in bdates if d < today]
    today_dates = [d for d in bdates if d == today]

    # ── Tier 0: CurveStore Parquet fast path (Eris EOD) ──
    if not ignore_cache and past_dates:
        try:
            store = self._get_curve_store()
            import pandas as _pd

            day_dfs = []
            for d in past_dates:
                day_df = store.read_raw_day(curve_name, d)
                if not day_df.empty:
                    day_dfs.append(day_df)

            if len(day_dfs) >= len(past_dates):
                parquet_df = _pd.concat(day_dfs, ignore_index=True)
                # Reconstruct rl.Curves from Parquet
                curves_by_ts = store.reconstruct_curves_batch(parquet_df, cfg=None)

                # Map back to trading dates
                parquet_by_date = {}
                for ts_key, rl_curve in curves_by_ts.items():
                    if hasattr(ts_key, "date"):
                        td = ts_key.date() if callable(ts_key.date) else ts_key.date
                    else:
                        td = _to_date(ts_key)
                    parquet_by_date[td] = rl_curve

                for ref_date in past_dates:
                    rl_curve = parquet_by_date.get(ref_date)
                    if rl_curve is None:
                        continue
                    fixings_series = _fetch_fixings(
                        as_of_date=ref_date, curve_name=curve_name,
                        force_refresh=self.force_refresh_fixings,
                    ).sort_index()
                    fixings_series = fixings_series[fixings_series.index.date < ref_date] * 100.0
                    out[ref_date] = RLIRSwapCurve(
                        rl_curve_id=curve_name,
                        rl_curve_handle=rl_curve,
                        fixings=fixings_series,
                        meta_data={"timestamp": ref_date},
                    )

                # If all past dates resolved, just handle today and return
                if len([d for d in past_dates if d in out]) >= len(past_dates):
                    # Handle today separately (live fetch)
                    for ref_date in today_dates:
                        _, rl_json_live, ts_live = self._rl_curve_cache.get_eris_eod_live_rl_basic(
                            curve_id=f"{self.source}-{curve_name}-live",
                            as_of="live",
                            force_refresh=True if ignore_cache else False,
                            fetcher_kwargs={"show_tqdm": True},
                        )
                        fixings_series = _fetch_fixings(
                            as_of_date=ref_date, curve_name=curve_name,
                            force_refresh=self.force_refresh_fixings,
                        ).sort_index()
                        fixings_series = fixings_series[fixings_series.index.date < ref_date] * 100.0
                        out[ref_date] = RLIRSwapCurve(
                            rl_curve_id=curve_name,
                            rl_curve_handle=from_json(rl_json_live),
                            fixings=fixings_series,
                            meta_data={"timestamp": ts_live},
                        )
                    return out
        except Exception as _tier0_exc:
            import logging as _logging
            _logging.getLogger(__name__).debug(
                "Eris CurveStore Tier 0 fast path failed: %s", _tier0_exc,
            )

    # ── Tier 1+2: diskcache + HTTP fallback (existing code unchanged) ──
    built_json: Dict[datetime.date, str] = {}
    # ... (rest of existing code stays the same)
```


## Task 6: Hook CurveStore write into Eris RL fetcher

**Files:**
- Modify: `MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/ErisFuturesFetcher.py`

**Step 1: Add CurveStore write after building rl.Curve in `fetch_intraday_discount_curve` (bulk bdates path)**

After `curves[tday] = curve` (line ~554), add a best-effort write to CurveStore:

```python
# Write to CurveStore for Tier 0 fast path
try:
    from Caching.curve_store import CurveSnapshot, CurveStore
    snap = CurveSnapshot.from_eris_df(
        df, trading_date=tday, curve_name="USD-SOFR-1D",
        source_variant="ERIS_RL_BASIC_NOJUMPS" if no_jumps_just_interp else "ERIS_RL_BASIC",
    )
    CurveStore.default().write_day("USD-SOFR-1D", tday, [snap])
except Exception:
    pass
```


## Task 7: Add `reconstruct_curve` support for Eris (no `cfg` / no mixed interpolation)

**Files:**
- Modify: `Caching/curve_store.py`

**Step 1: Make `reconstruct_curve` work without `cfg`**

The existing `reconstruct_curve` requires `cfg` for STIRF mixed interpolation. For Eris curves, `cfg=None` and `source_variant` starts with `ERIS`. The method already works without `cfg` (the mixed interpolation block is guarded by `if cfg and cfg.get("mixed_interpolation")`), but verify the `reference_key` lookup path works for Eris.

For Eris, `reference_key` will be `"USD-SOFR-1D"` which IS in `RATESLIB_CURVE_DEFINITIONS`. Confirm this reconstructs correctly (convention: act360, calendar: nyc, modifier: mf). No code change needed here — just verify.

**Step 2: Run manual verification**

After export (Task 4), test:
```python
from Caching.curve_store import CurveStore
import datetime

store = CurveStore()
df = store.read_raw_day("USD-SOFR-1D", datetime.date(2024, 6, 15))
print(df.shape, df.columns.tolist())

# RL reconstruction
curves = store.reconstruct_curves_batch(df, cfg=None)
print(len(curves), "curves reconstructed")

# QL reconstruction
ql_curves = store.reconstruct_ql_curves_batch(df)
print(len(ql_curves), "QL curves reconstructed")
```

