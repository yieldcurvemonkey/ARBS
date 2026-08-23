"""Timing + syntax probe for the leg-history warm.

Decides the architecture: if per-leg UnifiedQuery through TimeseriesBuilder is
cheap enough we warm ~70 leg series once and compose every structure level as a
linear combination of legs. If it is not, we fall back to per-date curve builds.
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

NY = pytz.timezone("America/New_York")
start = NY.localize(datetime.datetime(2025, 8, 21, 17, 0))
end = NY.localize(datetime.datetime(2026, 8, 21, 17, 0))

mdp = IRSwapsMDP(source="citivelo_excel_rl")
tb = TimeseriesBuilder()
router = {"IRS": IRSwapsTB(mdp, show_tqdm=False)}

# spot legs and forward legs, lowercase concatenated shorthand
probe = ["2y", "10y", "30y", "5y10y", "10y10y", "20y10y"]
t0 = time.time()
df = tb.get_timeseries(
    start=start, end=end,
    queries=[UnifiedQuery(curve="USD-SOFR-1D", tenor=t, value=UnifiedValue.IRS_RATE)
             for t in probe],
    n_jobs=8, routers=router,
)
dt = time.time() - t0
print(f"{len(probe)} legs, {len(df)} dates in {dt:.1f}s  -> {dt/len(probe):.1f}s per leg")
print(df.tail(3).round(3).to_string())
print("\ncolumns:", list(df.columns))
