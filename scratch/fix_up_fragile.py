"""Measure the FLAG_SIGN_FRAGILE claim on the real fee-bearing flow sample.

dealer_sign = sign(dev) * sign(z),  z = |dev| - u - b0.  As a function of the
true deviation the edge is  dev - sign(dev)*c  with  c = u + b0, so sign(edge)
changes at dev in {-c, 0, +c}.  Distance to 0 is |dev|; distance to +-c is |z|.
So the sign is fragile iff min(|dev|, |z|) is inside the mid error.
"""
import numpy as np
import pandas as pd

S = 0.2543          # measured mid sigma, bp
MULT = 2.0

d = pd.read_csv("scratch/uf02_flow_fee.csv")
d = d[d["error"].isna()].copy()
d["pv01"] = d["pv01"].abs()
u = d["other_payment_ufro"].fillna(0.0)
p = d["pkg_ptp"].abs().fillna(0.0)
U = np.where(p > 1000.0, p, u)
d = d[U > 0].copy()
U = U[U > 0]

dev = (-d["npv_pay"] / d["pv01"]).to_numpy()
u_bps = U / d["pv01"].to_numpy()
z = np.abs(dev) - u_bps

old = (np.abs(dev) <= MULT * S) & (u_bps > np.abs(dev))
new = np.minimum(np.abs(dev), np.abs(z)) <= MULT * S

n = len(d)
print(f"n = {n}   mid sigma = {S} bp   FRAGILE_SIGMA_MULT = {MULT}")
print(f"  OLD flag  |dev| <= {MULT}s and u > |dev| : {old.mean():.3f}  (n={old.sum()})")
print(f"  NEW flag  min(|dev|,|z|) <= {MULT}s      : {new.mean():.3f}  (n={new.sum()})")
unflagged_coinflip = (~old) & (np.abs(z) <= S)
print(f"  unflagged by OLD but |z| <= 1s          : {unflagged_coinflip.mean():.3f} "
      f" (n={unflagged_coinflip.sum()})  median |z| = "
      f"{np.median(np.abs(z[unflagged_coinflip])):.3f} bp")
print(f"  median |z| over all                     : {np.median(np.abs(z)):.3f} bp")
print(f"  frac |z| <= 1s                          : {(np.abs(z) <= S).mean():.3f}")
print(f"  frac |dev| <= 1s                        : {(np.abs(dev) <= S).mean():.3f}")
print(f"  NEW flag at 1 sigma                     : "
      f"{(np.minimum(np.abs(dev), np.abs(z)) <= S).mean():.3f}")
missed = new & ~old
print(f"  NEW fires where OLD did not             : {missed.mean():.3f} (n={missed.sum()})")
lost = old & ~new
print(f"  OLD fired where NEW does not            : {lost.sum()} rows")
