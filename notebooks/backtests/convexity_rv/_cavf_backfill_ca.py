r"""CA-vs-fly block: backfill the full convexity-adjustment panel via the TB path.

Every label is priced through ``IRSwapsTB.sfr_cvx_adj`` -- the repaired
Query/MDP/TimeseriesBuilder route (Q/Q matched swap, no ``_as_percent``
heuristic, ``fill=False``) -- so the panel this block trades from is the same
series the production timeseries path serves, not a second implementation.

Labels: the five pack colours, twenty constant-maturity outright ranks, and the
two 16-quarter bundle windows. Chunked by year so a crash loses one chunk, and
the TB's own mapping cache makes any re-run incremental.

Output: notebooks/data/convexity_rv/cavf_ca_panel.parquet  (wide, date-indexed)
        notebooks/data/convexity_rv/cavf_ca_failures.json  (per-label ledger)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)
OUT = DATA / "cavf_ca_panel.parquet"
LEDGER = DATA / "cavf_ca_failures.json"

LABELS = (["WHITES", "REDS", "GREENS", "BLUES", "GOLDS"]
          + [f"SFR{i}" for i in range(1, 21)]
          + ["BUNDLE1", "BUNDLE2"]                       # legacy 16q windows
          + ["BUNDLE2Y", "BUNDLE3Y", "BUNDLE4Y", "BUNDLE5Y"])  # CME bundles

START, END = dt.date(2021, 1, 4), dt.date(2026, 8, 21)

# The house preference for the main curve MDP. Measured bit-identical to the
# "CITIVELO_EXCEL" spelling on the CA path (max |diff| 0.0 bp) -- both live in
# CITIVELO_EXCEL_RL_TOKENS -- but the TB cache stem embeds the token, so keep
# one spelling everywhere.
curve_mdp = IRSwapsMDP(source="citivelo_excel_rl")
tb = IRSwapsTB(curve_mdp, show_tqdm=False, use_ts_cache=False)

frames: list[pd.DataFrame] = []
failures: dict[str, dict] = {}
t0 = time.time()
for y in range(START.year, END.year + 1):
    a = max(START, dt.date(y, 1, 1))
    b = min(END, dt.date(y, 12, 31))
    t1 = time.time()
    df = tb.sfr_cvx_adj(LABELS, a, b)
    nfail = {k: len(v) for k, v in tb.sfr_cvx_adj_failures.items() if v}
    for k, v in tb.sfr_cvx_adj_failures.items():
        if v:
            failures.setdefault(k, {}).update(v)
    frames.append(df)
    print(f"{y}: {df.shape[0]} dates x {df.shape[1]} cols "
          f"({time.time()-t1:.0f}s)  failures: {nfail if nfail else 'none'}")

panel = pd.concat(frames).sort_index()
panel = panel[~panel.index.duplicated(keep="last")]
panel.to_parquet(OUT)
LEDGER.write_text(json.dumps(failures, indent=1, default=str))
print(f"\nwrote {OUT}  {panel.shape}  {panel.index.min().date()}..{panel.index.max().date()}")
print("non-null per column:")
print(panel.notna().sum().to_string())
print(f"total {time.time()-t0:.0f}s")
tb.close()
