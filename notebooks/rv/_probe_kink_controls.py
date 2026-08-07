"""Probe: WHAT is doing the work in the 6m meeting-residual result?

The meeting residual turns a -43.5bp best config into a +187.2bp one on the 6m
fly. Three things could be responsible and only one of them is the thesis:

A  the standardisation -- ``scale_only`` keeps the model's zero, a z-score
   re-centres on a trailing mean. Control: the RAW fly, scale-only.
B  smoothing of any kind -- control: a decoy calendar (wrong phase, and evenly
   spaced) and a cubic spline in slot index.
E  the FOMC meeting structure itself -- the thesis.

Same grid, same engine, same costs for every one.
"""
import datetime
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "notebooks" / "backtests"))

import numpy as np
import pandas as pd

pd.set_option("display.width", 240, "display.max_columns", 60)

import sfr_kink_fade_common as K
from RVUtils.MeanRev import MRConfig, grid_search
from RVUtils.MeanRev.meetings import fomc_decisions, meeting_residual_panel
from RVUtils.MeanRev.signals import (
    curvefit_residual_signal, scale_only_zscore, structure_signal_from_slots,
    zscore_signal,
)

t0 = time.time()
lab = K.load_kink_lab("6m", "liquid16", lam=100.0)
levels, gate, st, c = lab["levels"], lab["gate"], lab["struct"], lab["contracts"]
slot_panel = lab["slot_panel"]
REAL = fomc_decisions(datetime.date(2017, 1, 1), datetime.date(2032, 12, 31))


def resid_fly(meetings, lam):
    r = meeting_residual_panel(c, meetings=meetings, lam=lam, max_slot=16)
    return structure_signal_from_slots(r, st, scale=1.0).reindex(
        index=levels.index, columns=levels.columns)


TARGET_SD = None      # set from the real calendar, then matched by the decoys


def tune_lam(meetings, target, lo=0.05, hi=1e6, iters=24):
    for _ in range(iters):
        mid = float(np.sqrt(lo * hi))
        if float(resid_fly(meetings, mid).stack().std()) < target:
            lo = mid
        else:
            hi = mid
    return float(np.sqrt(lo * hi))


real = resid_fly(REAL, 100.0)
TARGET_SD = float(real.stack().std())
print(f"real-calendar residual fly sd = {TARGET_SD:.3f}bp "
      f"(raw fly sd {levels.stack().std():.3f}bp)", flush=True)

shift21 = [d + datetime.timedelta(days=21) for d in REAL]
shift45 = [d + datetime.timedelta(days=45) for d in REAL]
evenly = [datetime.date(2018, 1, 31) + datetime.timedelta(days=int(round(45.656 * i)))
          for i in range(140)]

panels = {"E. real FOMC calendar": real}
for nm, mt in (("B1. calendar shifted +21d", shift21),
               ("B2. calendar shifted +45d", shift45),
               ("B3. evenly spaced 8/yr", evenly)):
    lam = tune_lam(mt, TARGET_SD)
    panels[nm] = resid_fly(mt, lam)
    print(f"  {nm}: lam={lam:.1f} -> sd {panels[nm].stack().std():.3f}bp", flush=True)

sp = curvefit_residual_signal(slot_panel, st, form="spline", scale=100.0).reindex(
    index=levels.index, columns=levels.columns)
panels["B4. cubic spline in slot"] = sp
print(f"  B4. spline: sd {sp.stack().std():.3f}bp", flush=True)

BASE = MRConfig(lag=1, round_trip_cost_bp=2.0, n_packages=100, max_hold=63)
GRID = {"window": (60, 120, 250), "entry_z": (1.5, 2.0, 2.5),
        "exit_style": ("z0", "t10", "t21", "t42"),
        "direction": ("fade", "momentum")}

cases = [("A. RAW fly, scale-only", lambda L, window: scale_only_zscore(L, window=window)),
         ("A2. RAW fly, z-score", lambda L, window: zscore_signal(L, window=window))]
for nm, p in panels.items():
    cases.append((f"{nm}, scale-only",
                  (lambda pp: (lambda L, window: scale_only_zscore(pp, window=window)))(p)))

rows = []
for name, fn in cases:
    g = grid_search(GRID, levels=levels, signal=None, gate=gate, base=BASE,
                    signal_fn=fn)
    d = g["total_net_bp"]
    best = g.loc[d.idxmax()]
    fade = g[g["direction"] == "fade"]["total_net_bp"].median()
    mom = g[g["direction"] == "momentum"]["total_net_bp"].median()
    rows.append({"case": name, "n_configs": len(g), "median_net_bp": d.median(),
                 "pct_positive": float((d > 0).mean()), "best_net_bp": d.max(),
                 "best_n": int(best["n_trades"]),
                 "best_gross_bp": best["total_gross_bp"],
                 "best_avg_bp": best["avg_net_bp"], "best_hit": best["hit_rate"],
                 "best_sharpe": best["sharpe"], "best_config": best["config"],
                 "fade_median": fade, "mom_median": mom})
    print(f"  ran {name} ({time.time() - t0:.0f}s)", flush=True)

out = pd.DataFrame(rows)
print("\n=== WHAT IS DOING THE WORK? (6m fly, liquid16, 2.0bp round trip) ===",
      flush=True)
print(out[["case", "n_configs", "median_net_bp", "pct_positive", "best_net_bp",
           "best_n", "best_avg_bp", "best_hit", "best_sharpe", "fade_median",
           "mom_median"]].round(3).to_string(index=False), flush=True)
print("\nbest configs:", flush=True)
for _, r in out.iterrows():
    print(f"  {r['case']:38s} {r['best_config']}", flush=True)
print(f"\nDONE in {time.time() - t0:.0f}s", flush=True)
