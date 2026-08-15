"""Harvest constant-maturity UST futures-option vol from QuikStrike.

This is the one deliberately-networked job in the convexity work, and it exists
to close the gap the three-way study ran into: strat 1's structures are
long-end, the only listed vol available offline was SFR (short end), so the
long end -- where the curve looks cheap against swaptions on 100% of days --
had no listed benchmark at all.

Why this endpoint and not ``sabr_smile``. A ``sabr_smile`` miss fetches one HTTP
call PER STRIKE and there is no cached history behind it (measured: 0 STIR / 8
UST smiles over a 1,205-day x 28-contract key scan). ``qs_timeseries`` takes a
DATE RANGE and returns a whole daily series in one call -- measured at 2.6s for
a 3-month window. That is the difference between a 30-minute job and an
overnight crawl.

``ABPV`` is QuikStrike's annualised basis-point volatility: a NORMAL vol in
bp/yr on the underlying's YIELD, which is directly comparable to the swaption
cube's normal vols and to the curve's breakeven vol once both are put in bp/day.
Taking it constant-maturity (``US_30`` = 30-day constant maturity on the 30y
bond option) also removes the expiry sawtooth that a listed contract series
would otherwise carry into every regression.

Roots, mapped to the sectors strat 1 actually trades:

    US / ZB   30-year bond          <- the long-end benchmark
    UL / WN   Ultra Bond            <- the longest listed point available
    TN / UXY  Ultra 10-year
    TY / ZN   10-year
    FV / ZF   5-year
    TU / ZT   2-year

Behaviour: resumable (skips series already on disk unless --force), rate-limited,
chunked by year so a failure costs one year rather than the run, and it records
what it could NOT get as data rather than dropping it silently.

Usage::

    conda run -n stir python scripts/harvest_ust_listed_vol.py
    conda run -n stir python scripts/harvest_ust_listed_vol.py --roots US UL --days 30 90
    conda run -n stir python scripts/harvest_ust_listed_vol.py --start 2019-01-01 --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import logging
import os
import pathlib
import sys
import time
from typing import Dict, List, Optional, Tuple

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

OUT_DIR = REPO / "notebooks" / "data" / "convexity_rv"
PANEL = OUT_DIR / "ust_listed_vol.parquet"
COVERAGE = OUT_DIR / "ust_listed_vol_coverage.json"

#: Long end first -- if the run is cut short, the sectors strat 1 needs are done.
DEFAULT_ROOTS = ["US", "UL", "TN", "TY", "FV", "TU"]

#: Constant-maturity tenors in calendar days. 30 is the QuikStrike default and
#: the one proven to work; the others are attempted and recorded if absent.
DEFAULT_DAYS = [30, 60, 90, 180]

#: ABPV is the normal bp vol. ATM is the lognormal-style price vol and is kept
#: as a cross-check on units; HistVol30D gives a realised comparison for free.
DEFAULT_VALUE_TYPES = ["ABPV", "ATM", "HistVol30D"]

_SINK = io.StringIO()


def _chunks(start: datetime.date, end: datetime.date, months: int = 12):
    """Year-sized [from, to] windows so one failure costs one chunk."""
    out = []
    a = start
    while a <= end:
        b = min(a + pd.DateOffset(months=months) - pd.Timedelta(days=1), pd.Timestamp(end))
        out.append((a, b.date() if hasattr(b, "date") else b))
        a = (pd.Timestamp(a) + pd.DateOffset(months=months)).date()
    return out


def fetch_series(
    mdp,
    symbol: str,
    value_type: str,
    start: datetime.date,
    end: datetime.date,
    *,
    pause: float = 0.4,
) -> Tuple[Optional[pd.DataFrame], str]:
    """One (symbol, value_type) series over [start, end]. Returns (df, note)."""
    frames: List[pd.DataFrame] = []
    notes: List[str] = []
    for a, b in _chunks(start, end):
        req = {
            "endpoint": "qs_timeseries",
            "start": a,
            "end": b,
            "queries": [{"globex_symbol": symbol, "qv_value_type": value_type}],
        }
        try:
            with contextlib.redirect_stdout(_SINK), contextlib.redirect_stderr(_SINK):
                out = mdp.get_data(req)
            ts = (out or {}).get("qs_timeseries") or []
            if ts and isinstance(ts[0], pd.DataFrame) and not ts[0].empty:
                frames.append(ts[0])
            else:
                notes.append(f"{a:%Y}:empty")
        except Exception as e:  # noqa: BLE001 - a chunk failing is data, not a crash
            notes.append(f"{a:%Y}:{type(e).__name__}")
        time.sleep(pause)
    if not frames:
        return None, ";".join(notes) or "no data"
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df, ";".join(notes)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", nargs="*", default=DEFAULT_ROOTS)
    ap.add_argument("--days", nargs="*", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--value-types", nargs="*", default=DEFAULT_VALUE_TYPES)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-08-14")
    ap.add_argument("--pause", type=float, default=0.4,
                    help="seconds between calls; be a good citizen")
    ap.add_argument("--force", action="store_true", help="refetch series already on disk")
    ap.add_argument("--dry-run", action="store_true", help="list the plan and exit")
    a = ap.parse_args(argv)

    logging.disable(logging.WARNING)
    start = datetime.date.fromisoformat(a.start)
    end = datetime.date.fromisoformat(a.end)

    plan = [(f"{r}_{d}", vt) for r in a.roots for d in a.days for vt in a.value_types]
    print(f"plan: {len(plan)} series, {start} .. {end}, pause {a.pause}s")
    if a.dry_run:
        for s, vt in plan:
            print(f"  {s:<10} {vt}")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = pd.read_parquet(PANEL) if (PANEL.exists() and not a.force) else None
    have = set()
    if existing is not None and not existing.empty:
        have = set(map(tuple, existing[["symbol", "value_type"]].drop_duplicates().values))
        print(f"resuming: {len(have)} series already on disk")

    from MDP.USTFutures.USTFutureOptionMDP import USTFutureOptionMDP  # noqa: E402

    with contextlib.redirect_stdout(_SINK):
        mdp = USTFutureOptionMDP(source="USTFO_DUAL-QL")

    rows: List[pd.DataFrame] = [existing] if existing is not None else []
    cov: Dict[str, Dict] = {}
    t_all = time.time()
    for i, (sym, vt) in enumerate(plan, 1):
        if (sym, vt) in have:
            print(f"[{i}/{len(plan)}] {sym} {vt}: skip (on disk)")
            continue
        t0 = time.time()
        df, note = fetch_series(mdp, sym, vt, start, end, pause=a.pause)
        el = time.time() - t0
        if df is None or df.empty:
            print(f"[{i}/{len(plan)}] {sym} {vt}: NONE ({el:.0f}s) {note}")
            cov[f"{sym}|{vt}"] = {"n": 0, "note": note}
            continue
        col = df.columns[0]
        tidy = pd.DataFrame({
            "date": pd.to_datetime(df.index),
            "symbol": sym,
            "root": sym.split("_")[0],
            "cm_days": int(sym.split("_")[1]),
            "value_type": vt,
            "value": pd.to_numeric(df[col], errors="coerce").to_numpy(),
        })
        tidy = tidy.dropna(subset=["value"])
        rows.append(tidy)
        cov[f"{sym}|{vt}"] = {
            "n": int(len(tidy)),
            "first": str(tidy["date"].min().date()),
            "last": str(tidy["date"].max().date()),
            "median": float(tidy["value"].median()),
            "note": note,
        }
        print(f"[{i}/{len(plan)}] {sym} {vt}: {len(tidy):>5} rows "
              f"{tidy['date'].min():%Y-%m-%d}..{tidy['date'].max():%Y-%m-%d} "
              f"median {tidy['value'].median():.1f} ({el:.0f}s)")

        # Write through after every series so a kill costs one series.
        pd.concat(rows, ignore_index=True).to_parquet(PANEL, index=False)
        COVERAGE.write_text(json.dumps(cov, indent=1), encoding="utf-8")

    if rows:
        panel = pd.concat(rows, ignore_index=True)
        panel.to_parquet(PANEL, index=False)
        print(f"\nwrote {PANEL}  rows={len(panel):,}  "
              f"series={panel.groupby(['symbol','value_type']).ngroups}  "
              f"({time.time()-t_all:.0f}s)")
    COVERAGE.write_text(json.dumps(cov, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
