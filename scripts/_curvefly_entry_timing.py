"""Does the carry survive the entry level? And are carry and richness the same fact?

Two questions the rac column cannot answer:
  1. The steepener's level sits at the 90th percentile of its own 2y range. What
     is one year of mean reversion worth against one year of carry?
  2. Is high carry mechanically a property of an extreme level? If CR and the
     z-score are strongly related across the family, they are not two independent
     reasons to like a structure -- they are one fact counted twice.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
pd.set_option("display.width", 200)

lh = pd.read_parquet(REPO / "docs" / "curvefly" / "leg_history.parquet")
scr = pd.read_csv(REPO / "docs" / "curvefly" / "screen_full_2026-08-21.csv")

print("=== 1. entry level vs one year of carry ===")
for lab, (a, b), cr in [("10y10y/20y10y", ("10y10y", "20y10y"), 9.13),
                        ("10y10y/15y10y", ("10y10y", "15y10y"), 6.63),
                        ("5y10y/10y10y", ("5y10y", "10y10y"), 6.59)]:
    lvl = (lh[b] - lh[a]).dropna()
    cur, mu, sd = float(lvl.iloc[-1]), float(lvl.mean()), float(lvl.std())
    pct = float((lvl < cur).mean()) * 100
    gap = cur - mu
    print(f"\n{lab}")
    print(f"  level {cur:>8.2f}  2y mean {mu:>8.2f}  sd {sd:>6.2f}  "
          f"z {gap/sd:>+5.2f}  pctile {pct:>4.0f}%")
    print(f"  distance to the 2y mean : {-gap:>+7.2f}bp   <- what full reversion costs a")
    print(f"                                             long (steepener) position")
    print(f"  one year of carry       : {cr:>+7.2f}bp")
    print(f"  net if it fully reverts : {cr - gap:>+7.2f}bp over a year")
    # how fast has it actually reverted? half-life of the level's AR(1)
    x = lvl.dropna()
    dx = x.diff().dropna()
    xl = x.shift(1).dropna().loc[dx.index]
    beta = float(np.polyfit(xl - x.mean(), dx, 1)[0])
    hl = (np.log(2) / -beta / 252.0) if beta < 0 else np.inf
    print(f"  AR(1) half-life         : "
          + (f"{hl*12:>6.1f} months" if np.isfinite(hl) else "  no mean reversion"))

print("\n\n=== 2. are carry and richness the same fact? ===")
sub = scr[scr.kind == "curve_fwd_tenor"].dropna(subset=["cr_bp", "zs"])
r = float(np.corrcoef(sub.cr_bp, sub.zs)[0, 1])
print(f"forward-curve-same-tenor family, n={len(sub)}")
print(f"  corr(1y carry, level z-score) = {r:+.3f}")
if abs(r) < 0.3:
    print("  -> weakly related. Carry and entry level are close to INDEPENDENT")
    print("     reasons to like or dislike a structure, so ranking on carry does")
    print("     not smuggle in a level view. They must be judged separately.")
else:
    print("  -> strongly related: high carry is largely a property of an extreme")
    print("     level, and the two should NOT be treated as independent evidence.")
allk = scr.dropna(subset=["cr_bp", "zs"])
print(f"whole screen, n={len(allk)}: corr = "
      f"{float(np.corrcoef(allk.cr_bp, allk.zs)[0,1]):+.3f}")


print("\n\n=== 3. carry vs reversion AT THE ACTUAL HORIZON ===")
print("cr_net_rev assumes FULL reversion, which over-charges a slow structure.")
print("Fraction reverted over horizon h with half-life L is 1 - 2^(-h/L).\n")
print(f"{'structure':<16}{'half-life':>10}{'horizon':>9}{'carry':>8}{'drag':>8}{'net':>8}")
CASES = [("10y10y/20y10y", 9.13, -10.79, 3.1),
         ("10y10y/15y10y", 6.63, -7.75, 6.9),
         ("5y10y/10y10y", 6.59, -7.29, 4.5),
         ("5s10s30s", -5.80, 7.40, None)]
lh2 = pd.read_parquet(REPO / "docs" / "curvefly" / "leg_history.parquet")
f5 = (2 * lh2["10y"] - lh2["5y"] - lh2["30y"]).dropna()
dx = f5.diff().dropna(); xl = f5.shift(1).dropna().loc[dx.index]
b = float(np.polyfit(xl - f5.mean(), dx, 1)[0])
hl5 = (np.log(2) / -b / 21.0) if b < 0 else np.inf
CASES[-1] = ("5s10s30s", -5.80, 7.40, hl5)
for name, cr, drag, L in CASES:
    for h in (3.0, 4.5, 6.0, 12.0):
        frac = 1 - 2 ** (-h / L) if np.isfinite(L) else 1.0
        net = cr * h / 12.0 + drag * frac
        tag = name if h == 3.0 else ""
        hlt = f"{L:.1f}m" if h == 3.0 else ""
        print(f"{tag:<16}{hlt:>10}{h:>8.1f}m{cr*h/12:>8.2f}{drag*frac:>8.2f}{net:>8.2f}")
    print()
