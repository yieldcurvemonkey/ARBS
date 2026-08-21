r"""W2b — SOFR pack convexity against a swap fly, on the REPAIRED panel.

The previous block ran this on a panel whose deep end was mostly absent: Blues
had 49 usable dates in 2023 and Golds had 0 in 2026. After the 486-date warm and
the node-horizon rebuild, Blues carries 2,000 dates and Golds 1,715, so for the
first time the ranks Citi actually traded are in daily reach across 2021-2026.

Runs the four arms the comparison needs -- hedged and unhedged, each at zero cost
and at a real spread -- through ``strat2_sofr_convexity``'s own engine, so the
result is comparable with the block-1 numbers rather than being a second
implementation.
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
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import RVUtils.ConvexityRV.strat2_sofr_convexity as S2  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
DATA = REPO / "notebooks" / "data" / "convexity_rv"

START, END = dt.date(2021, 1, 1), dt.date(2026, 8, 20)

panel = pd.read_parquet(DATA / "strat2_q20_panel.parquet")
panel["date"] = pd.to_datetime(panel["date"])
panel = panel[panel["gate_ok"]
              & (panel["date"] >= pd.Timestamp(START))
              & (panel["date"] <= pd.Timestamp(END))].copy()
rates = pd.read_parquet(DATA / "strat2_q20_rates.parquet")
rates.index = pd.to_datetime(rates.index)

print(f"panel {panel.shape}, {panel['date'].nunique():,} dates "
      f"{panel['date'].min().date()}..{panel['date'].max().date()}")
print(f"rates {rates.shape}, columns {list(rates.columns)}")
print("usable dates per colour:")
print(panel.groupby("colour")["date"].nunique().to_string())

# ranks 2..17 so Blues (13) and Golds (17) are inside the fitted range; rank 1 is
# excluded structurally (the 3m roll differences against a nearer pack).
cfg = S2.Strat2Config(start=START, end=END, rank_start=2, n_packs=16,
                      n_contracts=20)
print(f"\nconfig: rank_start={cfg.rank_start} n_packs={cfg.n_packs} "
      f"n_contracts={cfg.n_contracts} rebalance={cfg.rebalance_freq} "
      f"hedge_enabled={cfg.hedge_enabled}")

t0 = time.time()
ts = S2.panel_timeseries(panel, cfg)
model = S2.model_timeseries(panel, cfg)
specs = S2.plan_epochs(panel, rates, cfg, ts=ts, model=model, verbose=False)
print(f"\n{len(specs)} epochs planned ({time.time()-t0:.0f}s)")
if not specs:
    print("NO EPOCHS -- planning failure, not a flat result")
    raise SystemExit(1)

from collections import Counter  # noqa: E402
print("packs traded:", Counter(s.pack for s in specs).most_common(8))
holds = [int(np.busday_count(s.entry, s.exit)) for s in specs if s.exit]
print(f"hold bdays: median {np.median(holds):.0f} mean {np.mean(holds):.0f} "
      f"max {max(holds)}")

days = pd.DatetimeIndex(sorted(panel["date"].unique()))
rows = []
for hedged in (False, True):
    # Block 1 quoted this book at 0 / 0.5 / 1 / 2 bp round trip and found 1bp
    # was the level at which both arms went negative. 0.5bp is the house
    # default elsewhere in the package, so both are run.
    for cost_bp, tag in ((0.0, "zero_cost"), (0.5, "base"), (1.0, "cost_1bp")):
        from dataclasses import replace as _rep
        c = _rep(cfg, cost_bp_per_roundtrip=cost_bp)
        t1 = time.time()
        bt = S2.run_backtest(specs, c, hedged=hedged, trading_days=days,
                             show_progress=False)
        S2.assert_ran(bt, specs, hedged=hedged, expect_days=len(days))
        eq = pd.Series(bt.mtm_history).sort_index()
        eq.index = pd.to_datetime(eq.index)
        r = eq.diff().dropna()
        span = (eq.index[-1] - eq.index[0]).days / 365.25
        sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan
        name = f"{'hedged' if hedged else 'unhedged'}_{tag}"
        print(f"\n=== {name} ===")
        print(f"  terminal {eq.iloc[-1]:>15,.0f}   ann Sharpe {sharpe:>7.3f}   "
              f"max DD {float((eq-eq.cummax()).min()):>15,.0f}   ({time.time()-t1:.0f}s)")
        eq.to_frame("equity").to_parquet(DATA / f"w2b_equity_{name}.parquet")
        rows.append({"arm": name, "hedged": hedged, "cost_bp": cost_bp,
                     "terminal": float(eq.iloc[-1]), "sharpe": sharpe,
                     "max_dd": float((eq - eq.cummax()).min()),
                     "span_years": span, "n_epochs": len(specs)})

out = pd.DataFrame(rows)
out.to_csv(DATA / "w2b_arms.csv", index=False)
(DATA / "w2b_run.json").write_text(json.dumps(
    {"config": {k: str(v) for k, v in cfg.__dict__.items()},
     "n_epochs": len(specs), "dates": len(days),
     "hold_bdays_median": float(np.median(holds))}, indent=1))
print(f"\n{out.to_string(index=False)}")
print(f"\nwrote {DATA / 'w2b_arms.csv'}   total {time.time()-t0:.0f}s")
