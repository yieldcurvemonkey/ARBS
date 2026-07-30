"""Is the back of the strip's 'fast mean reversion' just tick discretisation?

SR3 settles on a 0.005 price grid outside the final four months (0.0025 inside),
i.e. 0.5bp of rate. A fly is 2*belly - front - back, so it inherits a 0.5bp
lattice. SFR-14-15-16 has a standard deviation of ~0.5bp -- one tick. A series
that bounces between two adjacent lattice points is maximally 'mean-reverting'
by every estimator, and none of that is tradeable.

This quantifies it: distinct values, tick multiples, and the share of daily
changes that are exactly zero or exactly one tick.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

from RVUtils.mean_reversion import half_life, hurst_exponent

DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)

st = pd.read_parquet(DATA / "structures_3m.parquet")
st["as_of"] = pd.to_datetime(st["as_of"])
st = st[st["as_of"] >= "2022-01-03"]

print("=== settle grid of the raw contracts ===")
c = pd.read_parquet(DATA / "contracts.parquet")
c["as_of"] = pd.to_datetime(c["as_of"])
c = c[c["as_of"] >= "2022-01-03"]
d = np.sort(c["settle"].dropna().unique())
step = np.diff(d)
step = step[step > 1e-9]
print(f"distinct settles {len(d)}, min positive gap {step.min():.6f} price points "
      f"= {step.min() * 100:.3f}bp of rate")
frac_half = float(np.isclose(np.mod(c['settle'].dropna() * 1000, 5), 0).mean())
print(f"share of settles on the 0.005 grid: {frac_half:.3%}")

print("\n=== fly level lattice, by CM slot ===")
rows = []
for cm, g in st.groupby("cm_label_short"):
    v = g["value"].dropna()
    if len(v) < 200:
        continue
    uniq = np.sort(v.unique())
    gaps = np.diff(uniq)
    gaps = gaps[gaps > 1e-9]
    dv = g.sort_values(["key", "as_of"]).groupby("key")["value"].diff().dropna()
    rows.append({
        "cm": cm, "slot": g["cm_slot"].iloc[0], "n": len(v),
        "n_distinct": len(uniq), "sd_bp": v.std(),
        "min_gap_bp": gaps.min() if len(gaps) else np.nan,
        "sd_in_ticks": v.std() / 0.5,
        "pct_dv_zero": float((dv.abs() < 1e-9).mean()),
        "pct_dv_one_tick": float((np.isclose(dv.abs(), 0.5)).mean()),
        "pct_dv_le_one_tick": float((dv.abs() <= 0.5 + 1e-9).mean()),
        "half_life_d": half_life(v),
        "hurst": hurst_exponent(v, max_lag=20),
    })
t = pd.DataFrame(rows).sort_values("slot")
print(t.round(3).to_string(index=False))

print("\n=== interpretation ===")
tight = t[t["sd_in_ticks"] < 2.0]
print(f"slots whose ENTIRE standard deviation is under two 0.5bp ticks: "
      f"{len(tight)}/{len(t)}")
if len(tight):
    print("  " + ", ".join(f"{r.cm} (sd={r.sd_bp:.2f}bp = {r.sd_in_ticks:.1f} ticks, "
                           f"{r.n_distinct} distinct values, hl={r.half_life_d:.1f}d)"
                           for r in tight.itertuples()))
print("\nFor these slots the fly is a 3-5 point lattice. Every mean-reversion "
      "estimator reads a lattice as strongly reverting, and none of it is "
      "tradeable: one tick IS 0.5bp and the round trip is 1.5bp = 3 ticks.")
