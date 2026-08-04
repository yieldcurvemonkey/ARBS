"""Scope the intraday data before designing anything on top of it.

The kink-fade labs mark on EOD settles. Moving to intraday changes the
economics in a way that is arithmetic, not empirical: **the round trip costs the
same at every frequency, but E|move| shrinks with the horizon.** So the only
questions worth asking first are about the DATA, because they bound everything:

1. How far back does Barchart serve 240-minute bars? (EOD history is 2018-01;
   intraday retention is usually far shorter, and a short panel caps the power
   of any league table built on it.)
2. How many bars per session, and in which hours do they actually print?
3. **What fraction of bars are no-trade or stale?** This is the load-bearing
   one. A package built from legs that did not trade in the same bar shows
   mean reversion that is pure staleness, and back-rank ZQ/SR3 contracts are
   quiet for most of the day.
4. What does the tick lattice look like intraday? At 0.5bp ticks a 4h move of
   a fraction of a tick is not a move.

Deliberately small: a handful of symbols, one call, so the shared 55/60s
intraday budget is nowhere near stressed.

Run: conda run -n stir python notebooks/rv/_probe_stir_intraday_coverage.py
"""
import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import pytz

pd.set_option("display.width", 250, "display.max_columns", 40)

# Barchart's intraday endpoint stamps in exchange-local time and REJECTS naive
# bounds (the EOD endpoint accepts them, which is an easy trap). Futures are
# Central.
CME_TZ = pytz.timezone("America/Chicago")

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP, _to_barchart_symbol

# front, mid and back of each strip: coverage is expected to fall off hard with
# rank, and the whole point is to find out where it becomes unusable.
SYMBOLS = ["SR3U26", "SR3Z26", "SR3U27", "SR3U28",
           "ZQU26", "ZQZ26", "ZQM27", "ZQZ27"]
INTERVAL = 240
LOOKBACK_YEARS = 6


def main() -> int:
    end = CME_TZ.localize(datetime.datetime(2026, 7, 30, 23, 59))
    start = CME_TZ.localize(datetime.datetime(2026, 7, 30, 23, 59)
                            - datetime.timedelta(days=365 * LOOKBACK_YEARS))
    bsyms = [_to_barchart_symbol(s) for s in SYMBOLS]
    print(f"requesting interval={INTERVAL}min for {bsyms}")
    print(f"  window {start.date()} -> {end.date()} ({LOOKBACK_YEARS}y)\n", flush=True)

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    bcf = mdp._get_barchart_fetcher(required_concurrency=len(bsyms) + 1)
    frames = bcf.barchart_timeseries_api(
        barchart_symbols=bsyms, start_date=start, end_date=end,
        interval=INTERVAL, one_df=False, show_tqdm=True)

    if isinstance(frames, pd.DataFrame):
        frames = {bsyms[0]: frames}

    print("\n" + "=" * 100)
    print("COVERAGE BY SYMBOL")
    print("=" * 100, flush=True)
    rows, keep = [], {}
    for sym, df in (frames.items() if isinstance(frames, dict)
                    else zip(bsyms, frames)):
        if df is None or len(df) == 0:
            rows.append({"symbol": sym, "bars": 0})
            continue
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index(df.columns[0])
        df = df.sort_index()
        keep[sym] = df
        c = df["Close"].astype(float)
        d = c.diff()
        v = df["Volume"].astype(float) if "Volume" in df else pd.Series(np.nan, index=df.index)
        rows.append({
            "symbol": sym, "bars": len(df),
            "first": df.index[0].date(), "last": df.index[-1].date(),
            "span_days": (df.index[-1] - df.index[0]).days,
            "bars_per_day": round(len(df) / max((df.index[-1] - df.index[0]).days, 1), 2),
            "pct_zero_vol": round(float((v.fillna(0) == 0).mean()), 3),
            "pct_unchanged": round(float((d.abs() < 1e-12).mean()), 3),
            "sd_bp": round(float(d.std() * 100), 3),
            "median_abs_move_bp": round(float(d.abs().median() * 100), 3),
        })
    cov = pd.DataFrame(rows)
    print(cov.to_string(index=False), flush=True)

    if not keep:
        print("\nNO INTRADAY DATA RETURNED -- the study cannot be built on this source.")
        return 1

    print("\n" + "=" * 100)
    print("BAR CLOCK -- when do 4h bars actually stamp? (exchange tz)")
    print("=" * 100, flush=True)
    for sym, df in list(keep.items())[:3]:
        hrs = pd.Series(df.index.hour).value_counts().sort_index()
        print(f"  {sym}: {dict(hrs)}", flush=True)

    print("\n" + "=" * 100)
    print("THE STALENESS QUESTION")
    print("=" * 100, flush=True)
    print("""A kink is a cross-contract object. If leg A prints in a bar and leg B
does not, the package's change is leg A's change alone -- and it reverts next
bar when B catches up. That is not mean reversion, it is a data artifact, and it
is the single most likely way an intraday version of this study produces a
spectacular false positive.""", flush=True)
    common = None
    for sym, df in keep.items():
        idx = df.index
        common = idx if common is None else common.intersection(idx)
    print(f"\n  bars present in EVERY probed symbol: {len(common) if common is not None else 0}")
    for sym, df in keep.items():
        print(f"    {sym}: {len(df)} bars, {len(df.index.intersection(common))} shared"
              if common is not None else "", flush=True)

    # joint no-trade: fraction of shared bars where at least one leg is unchanged
    if common is not None and len(common) > 10:
        sub = pd.DataFrame({s: keep[s]["Close"].astype(float).reindex(common)
                            for s in keep})
        d = sub.diff()
        any_stale = (d.abs() < 1e-12).any(axis=1)
        print(f"\n  shared bars where >=1 leg did not move: {float(any_stale.mean()):.1%}")
        print(f"  shared bars where ALL legs moved:        {float((~any_stale).mean()):.1%}")

    out = REPO / "notebooks" / "data" / "stir_intraday"
    out.mkdir(parents=True, exist_ok=True)
    cov.to_csv(out / "coverage_probe.csv", index=False)
    print(f"\nwrote {out / 'coverage_probe.csv'}")
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
