"""Probe: on the 6m fly, where the oracle clears the round trip, does anything pay?

The pond test says a 6m butterfly moves 4.3bp over 21 days on the days a kink
signal fires, against a 2.0bp round trip. That is the first structure in either
lab whose ceiling is comfortably above cost. This runs the grid to find out
whether any of that survives the sign call.
"""
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
from RVUtils.MeanRev.signals import (
    scale_only_zscore, structure_signal_from_slots, zscore_signal,
)

t0 = time.time()
lab = K.load_kink_lab("6m", "liquid16", lam=100.0)
levels, gate, st = lab["levels"], lab["gate"], lab["struct"]
mres = structure_signal_from_slots(lab["resid_slots"], st, scale=1.0).reindex(
    index=levels.index, columns=levels.columns)
tilt = lab["tilted"]["level"].reindex(index=levels.index, columns=levels.columns)
print(f"loaded {levels.shape} in {time.time() - t0:.1f}s", flush=True)

SIGNALS = {
    "K0 raw z": lambda L, window: zscore_signal(L, window=window),
    "K1 resid scale": lambda L, window: scale_only_zscore(mres, window=window),
    "K1z resid z": lambda L, window: zscore_signal(mres, window=window),
    "K2 tilted z": lambda L, window: zscore_signal(tilt, window=window),
}

BASE = MRConfig(lag=1, round_trip_cost_bp=2.0, n_packages=100, max_hold=63)
GRID = {"window": (60, 120, 250), "entry_z": (1.5, 2.0, 2.5),
        "exit_style": ("z0", "t10", "t21", "t42"),
        "direction": ("fade", "momentum")}

for name, fn in SIGNALS.items():
    g = grid_search(GRID, levels=levels, signal=None, gate=gate, base=BASE,
                    signal_fn=fn)
    d = g["total_net_bp"]
    best = g.loc[d.idxmax()]
    fade = g[g["direction"] == "fade"]["total_net_bp"]
    mom = g[g["direction"] == "momentum"]["total_net_bp"]
    print(f"\n{name}: {len(g)} configs | median {d.median():+.1f}bp | "
          f"{(d > 0).mean():.0%} positive | best {d.max():+.1f}bp", flush=True)
    print(f"  sign test: fade median {fade.median():+.1f}  "
          f"momentum median {mom.median():+.1f}", flush=True)
    print(f"  best: {best['config']}  n={int(best['n_trades'])}  "
          f"gross {best['total_gross_bp']:+.1f}  net {best['total_net_bp']:+.1f}  "
          f"hit {best['hit_rate']:.0%}  SR {best['sharpe']:+.2f}", flush=True)
    top = g.sort_values("total_net_bp", ascending=False).head(5)
    print(top[["window", "entry_z", "exit_style", "direction", "n_trades",
               "hit_rate", "avg_net_bp", "total_net_bp", "sharpe"]]
          .round(3).to_string(index=False), flush=True)

print(f"\nDONE in {time.time() - t0:.0f}s", flush=True)
