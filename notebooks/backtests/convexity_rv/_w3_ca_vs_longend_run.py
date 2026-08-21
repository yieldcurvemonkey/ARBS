r"""W3 — STIR convexity adjustment against long-end curve convexity, as vol RV.

Both legs are curve-implied vol in bp/day: the pack CA inverted through Ho-Lee,
and the ultra-long forward flattener's daily breakeven. Neither is an option
price, so the spread between them is what the two markets disagree about.

The diagnostics run BEFORE the trade, and the change-correlation is the one that
decides whether there is a relationship at all.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ConvexityRV import w3_ca_vs_longend as W3  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
DATA = REPO / "notebooks" / "data" / "convexity_rv"

cfg = W3.W3Config()
print(f"config: {cfg.to_dict()}")

panel = pd.read_parquet(DATA / "strat2_q20_panel.parquet")
panel["date"] = pd.to_datetime(panel["date"])
panel = panel[panel["gate_ok"]]

rac = pd.read_parquet(DATA / "rac_screen_panel.parquet")
rac["date"] = pd.to_datetime(rac["date"])

rows = []
for colour in ("Reds", "Greens", "Blues", "Golds"):
    c = W3.W3Config(colour=colour, pair=cfg.pair)
    stir = W3.stir_implied_vol_series(panel, c)
    if stir.empty:
        print(f"{colour}: no STIR implied-vol series")
        continue
    for pair in ("15Yx5Y/20Yx10Y", "10Yx10Y/20Yx10Y", "15Yx5Y/25Yx10Y",
                 "20Yx5Y/25Yx5Y"):
        sub = rac[rac["pair"] == pair]
        if sub.empty:
            continue
        long_be = (sub.set_index("date")["be_daily_analytic"]
                      .replace(0.0, np.nan).dropna().sort_index())
        diag = W3.link_diagnostics(stir, long_be)
        sp = W3.build_vol_spread_panel(stir, long_be, c)
        st = W3.entry_state(sp, c) if not sp.empty else pd.Series(dtype=int)
        on = int((st != 0).sum()) if len(st) else 0
        rows.append({"colour": colour, "pair": pair, **diag,
                     "spread_mean": float(sp["spread"].mean()) if not sp.empty else np.nan,
                     "spread_sd": float(sp["spread"].std()) if not sp.empty else np.nan,
                     "days_on": on,
                     "days_total": int(len(st)),
                     "frac_on": float(on / len(st)) if len(st) else np.nan})

res = pd.DataFrame(rows)
pd.set_option("display.width", 220, "display.max_columns", 30)
print("\n=== link diagnostics: does the STIR leg move with the long-end leg? ===")
cols = ["colour", "pair", "n", "corr_levels", "corr_changes", "beta_changes",
        "stir_mean", "long_mean", "spread_mean", "spread_sd",
        "spread_adf_p", "spread_half_life_days", "frac_on"]
print(res[cols].round(4).to_string(index=False))

print("\nCHANGE correlation is the one that matters. Two trending series")
print("correlate in levels for reasons that are not tradable.")
best = res.loc[res["corr_changes"].abs().idxmax()] if len(res) else None
if best is not None:
    print(f"\nstrongest change-correlation: {best['colour']} vs {best['pair']} "
          f"= {best['corr_changes']:+.4f} on n={int(best['n'])}")

res.to_csv(DATA / "w3_link_diagnostics.csv", index=False)
print(f"\nwrote {DATA / 'w3_link_diagnostics.csv'}")

print()
print("STATIONARITY: a z-score entry ASSUMES the spread reverts. ADF p > 0.05")
print("means a unit root cannot be rejected, i.e. the spread is a random walk")
print("and the signal is fitting the sampling distribution of one.")
if len(res):
    nonstat = int((res["spread_adf_p"] > 0.05).sum())
    print(f"  {nonstat} of {len(res)} spreads FAIL to reject a unit root at 5%.")
    print(res[["colour", "pair", "spread_adf_p", "spread_half_life_days"]]
          .round(4).to_string(index=False))
