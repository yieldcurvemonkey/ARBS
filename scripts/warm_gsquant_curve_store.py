#!/usr/bin/env python
r"""Build the GS Quant USD curves and bank them in the CurveStore.

Why this exists
---------------
``IRSwapsMDP`` opts ``GSQUANT-RL`` into the CurveStore raw-curve and analytics fast
paths, and ``TimeseriesBuilder._build_irs_curve_store_curve_map`` **reads** that store
and returns ``{}`` on a miss -- it never builds. So the nightly's GS Quant job could only
price days somebody had already banked, and nothing in the nightly banked any:
``scripts/import_gsquant_curve_panel.py`` is a one-off CSV importer.

The consequence was invisible because it was not an error. Every retained run reported

    GSQUANT USD-OIS EOD   OK (68.6s, 0 rows x 0 cols)

with ``asset=USD-OIS`` in the store ending 2026-08-03 while ``asset=USD-SOFR-1D`` stayed
current. The job's only curve was USD-OIS, so it read an empty store, returned an empty
frame, and the runner called that success.

This is the missing half: the fetch/build/warm step that has to run BEFORE the pricing,
the same shape the Citi CurveStore job (job 8) uses.

What it writes
--------------
Per curve per business day, two partitions:

* the RAW curve -- node dates and discount factors, via ``store.write_day``
* the ANALYTICS frame -- par rates on the curve's analytics tenors, via
  ``store.write_analytics_day``

Both are needed. The TB has a fast path for each, and a day with raw but no analytics
still falls through.

Two things this gets right that the CSV importer could not
----------------------------------------------------------
**Conventions come from ``reference_key``, not the curve name.** The importer looks up
``RATESLIB_CURVE_DEFINITIONS[curve_name]`` directly, which works only for curves whose
name IS a rateslib key. ``USD-SOFR-1D-CME`` and its siblings are not: they resolve
through ``GSQUANT_CURVE_MAP[curve]["rl_basic"]["reference_key"]``, because the clearing
house changes whose curve it is and not the conventions it is built with.

**A curve that fails costs that curve, not the run.** Eight curves times a backfill
window is a lot of chances for one bad day, and the previous behaviour -- one exception
ending everything -- is how a warm silently stops covering half its assets.

Idempotent: a day already holding both partitions is skipped, so the nightly is a no-op
on a warm store and ``--overwrite`` is needed to rewrite one.

Run it
------
    python -m scripts.warm_gsquant_curve_store --start 2026-08-04 --end 2026-08-21
    python -m scripts.warm_gsquant_curve_store --curves USD-OIS,USD-OIS-CME --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd
import pytz
import rateslib as rl

from Caching.curve_analytics import (
    analytics_tenors_for_curve,
    build_analytics_frame,
    compute_session_minute,
)
from Caching.curve_store import CurveSnapshot, CurveStore
from MDP.IRSwaps.GSQUANT.rl_basic.build import (
    GSQUANT_CURVE_MAP,
    build_rl_basic_gsquant_curves,
)
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

log = logging.getLogger("gsquant-curve-warm")

_NY = pytz.timezone("America/New_York")
_CHI = pytz.timezone("America/Chicago")
_UTC = pytz.UTC

#: The curves the nightly prices. Kept here rather than imported from the warmer so this
#: script stands alone, and asserted against GSQUANT_CURVE_MAP at run time so the two
#: cannot drift apart silently.
DEFAULT_CURVES = (
    "USD-SOFR-1D",
    "USD-SOFR-1D-CME",
    "USD-OIS",
    "USD-OIS-CME",
    "USD-SOFR-1D-STIR-LCH",
    "USD-SOFR-1D-STIR-CME",
    "USD-OIS-STIR-LCH",
    "USD-OIS-STIR-CME",
)

#: The EOD stamp the curves are recorded at. 16:00 New York -- these are end-of-day
#: marks, and the store partitions on the trading date regardless, but the timestamp is
#: what ``session_minute`` and any intraday consumer read.
_EOD_HOUR, _EOD_MINUTE = 16, 0


def _reference_key(curve: str) -> str:
    """The rateslib definition a GS Quant curve is built with."""
    cfg = GSQUANT_CURVE_MAP[curve]["rl_basic"]
    return cfg["reference_key"]


def _curve_timestamp(as_of: dt.date) -> dt.datetime:
    return _NY.localize(dt.datetime(as_of.year, as_of.month, as_of.day, _EOD_HOUR, _EOD_MINUTE))


def _spot_start(as_of: dt.date, reference_key: str) -> Any:
    curve_def = RATESLIB_CURVE_DEFINITIONS[reference_key]
    cal = curve_def.get("Calendar")
    lag = int(curve_def.get("SettlementDays", 2) or 0)
    try:
        return rl.add_tenor(dt.datetime(as_of.year, as_of.month, as_of.day),
                            f"{lag}b", "F", cal)
    except Exception:
        return dt.datetime(as_of.year, as_of.month, as_of.day)


def _snapshot(curve: str, as_of: dt.date, rl_curve: Any, source_variant: str) -> CurveSnapshot:
    ts_local_ny = getattr(rl_curve, "timestamp", None) or _curve_timestamp(as_of)
    if ts_local_ny.tzinfo is None:
        ts_local_ny = _NY.localize(ts_local_ny)
    ts_utc = ts_local_ny.astimezone(_UTC)
    ts_chi = ts_utc.astimezone(_CHI)

    raw_nodes = rl_curve.nodes._nodes if hasattr(rl_curve.nodes, "_nodes") else dict(rl_curve.nodes)
    ordered = sorted(raw_nodes.keys())
    return CurveSnapshot(
        timestamp_utc=ts_utc,
        timestamp_local=ts_chi,
        trading_date=as_of,
        session_minute=compute_session_minute(ts_chi),
        curve_name=curve,
        cfg_hash="",
        # The rateslib definition, NOT the curve name: USD-OIS-CME is built with
        # USD-OIS conventions and a consumer needs to know which.
        reference_key=_reference_key(curve),
        interpolation=str(getattr(rl_curve, "interpolation", "log_linear") or "log_linear"),
        source_variant=source_variant,
        node_dates=[pd.Timestamp(d).date() for d in ordered],
        discount_factors=[float(raw_nodes[d]) for d in ordered],
    )


def _analytics(curve: str, as_of: dt.date, rl_curve: Any) -> pd.DataFrame:
    ts_local_ny = getattr(rl_curve, "timestamp", None) or _curve_timestamp(as_of)
    if ts_local_ny.tzinfo is None:
        ts_local_ny = _NY.localize(ts_local_ny)
    ts_utc = ts_local_ny.astimezone(_UTC)
    ref = _reference_key(curve)
    curve_def = RATESLIB_CURVE_DEFINITIONS[ref]
    spot = _spot_start(as_of, ref)

    row: Dict[str, Any] = {
        "timestamp_utc": ts_utc,
        "trading_date": as_of,
        "session_minute": compute_session_minute(ts_utc.astimezone(_CHI)),
    }
    priced = 0
    for tenor in analytics_tenors_for_curve(curve):
        value = float("nan")
        try:
            irs = rl.IRS(effective=spot, termination=str(tenor),
                         spec=curve_def["ReferenceRate"], curves=rl_curve)
            value = float(irs.rate(curves=rl_curve).real)
            priced += 1
        except Exception:
            # A tenor past this curve's support is EXPECTED for the STIR curves and is
            # not a failure of the day. It is recorded NaN, which is what a reader must
            # see rather than an extrapolated number.
            value = float("nan")
        row[f"par_rate_{tenor}"] = value
        row[f"rate_{tenor}"] = value
    if priced == 0:
        raise ValueError(f"{curve} {as_of}: no analytics tenor priced")
    return build_analytics_frame([row])


def business_days(start: dt.date, end: dt.date) -> List[dt.date]:
    return [d.date() for d in pd.bdate_range(start, end)]


def warm(
    *,
    start: dt.date,
    end: dt.date,
    curves: Sequence[str] = DEFAULT_CURVES,
    store: Optional[CurveStore] = None,
    overwrite: bool = False,
    dry_run: bool = False,
    max_workers: int = 4,
    source_variant: str = "GSQUANT_RL",
) -> Dict[str, Dict[str, int]]:
    """Build and bank every (curve, business day) that is not already complete."""
    store = store or CurveStore.default()
    unknown = [c for c in curves if c not in GSQUANT_CURVE_MAP]
    if unknown:
        raise KeyError(f"not in GSQUANT_CURVE_MAP: {unknown}")

    grid = business_days(start, end)
    log.info("GS Quant curve warm: %d curve(s) x %d business day(s), store %s",
             len(curves), len(grid), store.base_dir)

    summary: Dict[str, Dict[str, int]] = {}
    for curve in curves:
        need = [d for d in grid
                if overwrite or not (store.has_day(curve, d) and store.has_analytics_day(curve, d))]
        stats = {"needed": len(need), "written": 0, "failed": 0, "skipped": len(grid) - len(need)}
        summary[curve] = stats
        if not need:
            log.info("  %-22s already complete for all %d day(s)", curve, len(grid))
            continue
        if dry_run:
            log.info("  %-22s would build %d day(s): %s .. %s",
                     curve, len(need), need[0], need[-1])
            continue

        try:
            built = build_rl_basic_gsquant_curves(
                curve=curve, as_of_dates=need, max_workers=max_workers)
        except Exception as exc:  # noqa: BLE001 - one curve must not end the warm
            log.warning("  %-22s BUILD FAILED for the whole window (%s: %s)",
                        curve, type(exc).__name__, exc)
            stats["failed"] = len(need)
            continue

        for as_of in need:
            got = built.get(as_of)
            if not got:
                stats["failed"] += 1
                continue
            rl_curve = got[1] if isinstance(got, tuple) else got
            try:
                snap = _snapshot(curve, as_of, rl_curve, source_variant)
                frame = _analytics(curve, as_of, rl_curve)
                store.write_day(curve, as_of, [snap], overwrite=overwrite)
                store.write_analytics_day(curve, as_of, frame, overwrite=overwrite)
                stats["written"] += 1
            except Exception as exc:  # noqa: BLE001 - a bad day costs that day
                log.warning("  %-22s %s: %s: %s", curve, as_of, type(exc).__name__, exc)
                stats["failed"] += 1

        log.info("  %-22s %d written, %d skipped, %d failed",
                 curve, stats["written"], stats["skipped"], stats["failed"])

    tot_w = sum(s["written"] for s in summary.values())
    tot_f = sum(s["failed"] for s in summary.values())
    log.info("GS Quant curve warm done: %d curve-day(s) written, %d failed", tot_w, tot_f)
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Warm the GS Quant USD curves into the CurveStore")
    ap.add_argument("--start", type=dt.date.fromisoformat, default=None)
    ap.add_argument("--end", type=dt.date.fromisoformat, default=None)
    ap.add_argument("--curves", default=None, help="comma list; default all eight")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-workers", type=int, default=4)
    a = ap.parse_args(argv)

    end = a.end or dt.date.today()
    start = a.start or end
    curves = tuple(c.strip() for c in a.curves.split(",")) if a.curves else DEFAULT_CURVES
    out = warm(start=start, end=end, curves=curves, overwrite=a.overwrite,
               dry_run=a.dry_run, max_workers=a.max_workers)
    return 0 if all(s["failed"] == 0 for s in out.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
