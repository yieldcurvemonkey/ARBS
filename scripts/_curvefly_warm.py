"""Warm the LEG history once; every structure level composes from it linearly.

The screen needs history for ~70 legs, not for ~2,000 structures: a two-leg curve
is ``w.r`` and a fly is ``w.r`` with three weights, both linear in the leg rates.
So one TimeseriesBuilder pass over the legs serves curves, flies and any future
weighting scheme.

Uses the repo pattern: IRSwapsMDP -> IRSwapsTB router -> TimeseriesBuilder with
UnifiedQuery per leg. Tenor shorthand is lowercase-concatenated (``10y10y``)
throughout -- tenor CASE forks the cache symbol, so mixing ``10Y10Y`` in would
silently double the fetch and split the history.
"""
from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

import pandas as pd
import pytz

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
pd.set_option("display.width", 220)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402
from TB.TimeseriesBuilder import TimeseriesBuilder  # noqa: E402
from Query.Unified.UnifiedQuery import UnifiedQuery  # noqa: E402
from Query.Unified.registry import UnifiedValue  # noqa: E402
from RVUtils.CurveFlyScreener.universe import leg_universe, leg_label  # noqa: E402

NY = pytz.timezone("America/New_York")
START = NY.localize(datetime.datetime(2024, 8, 21, 17, 0))
END = NY.localize(datetime.datetime(2026, 8, 21, 17, 0))
OUT = REPO / "docs" / "curvefly" / "leg_history.parquet"

legs = leg_universe()
labels = [leg_label(l) for l in legs]
print(f"warming {len(legs)} legs, {START:%Y-%m-%d} -> {END:%Y-%m-%d}")

mdp = IRSwapsMDP(source="citivelo_excel_rl")
tb = TimeseriesBuilder()
t0 = time.time()
df = tb.get_timeseries(
    start=START, end=END,
    queries=[UnifiedQuery(curve="USD-SOFR-1D", tenor=t, value=UnifiedValue.IRS_RATE)
             for t in labels],
    n_jobs=8,
    routers={"IRS": IRSwapsTB(mdp, show_tqdm=False)},
)
print(f"fetched in {time.time()-t0:.0f}s, shape {df.shape}")

# columns come back as "USD-SOFR-1D {tenor} OUTRIGHT RATE" -- map back to the leg
ren, missing = {}, []
for lab in labels:
    col = f"USD-SOFR-1D {lab} OUTRIGHT RATE"
    if col in df.columns:
        ren[col] = lab
    else:
        missing.append(lab)
df = df[list(ren)].rename(columns=ren) * 100.0          # percent -> bp
if missing:
    print(f"NO SERIES for {len(missing)} legs: {missing}")

cov = df.notna().mean().sort_values()
print(f"\ncoverage: {len(df)} dates; median {cov.median():.0%}")
thin = cov[cov < 0.8]
if len(thin):
    print(f"THIN (<80% of dates), excluded from vol/z-scores:\n{(thin*100).round(0).to_string()}")
df.to_parquet(OUT)
print(f"\nwrote {OUT}  {df.shape}")
print(df.iloc[-1].round(2).to_string())
