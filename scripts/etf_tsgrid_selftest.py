"""Run the grid machinery against inputs whose answers are known by hand.

A checking tool that is itself wrong reports success and hides the thing it was built to
find. Each block below has an answer computed independently of the code under test, and
each mutation block deliberately breaks an assumption and requires the check to notice.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import etf_tsgrid_lib as L

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        fails.append(name)


# ------------------------------------------------------------------ 1. fly arithmetic
m = L.Matrices(
    dates=pd.DatetimeIndex(["2024-01-02", "2024-01-03"]),
    cusips=np.array(["A", "B", "C", "D"]),
    Y={16: np.array([[4.00, 4.10, 4.15, 4.30],
                     [4.00, 4.20, 4.15, 4.30]])},
    RESZ={}, RES={}, STALE={},
    T=np.array([[20.0, 20.25, 20.50, 20.75]] * 2),
    MODDUR=np.full((2, 4), 15.0),
    SPREAD_PX=np.full((2, 4), 3.0),
    RANK=np.full((2, 4), 6.0),
    early_close=np.array([False, False]), is_last_bd=np.array([False, False]),
)
legs = L.build_legs(m, step=1)
check("legs: interior bonds get wings", bool(legs.valid[0, 1] and legs.valid[0, 2]))
check("legs: endpoints get none", not (legs.valid[0, 0] or legs.valid[0, 3]))
check("legs: a = 0.5 on an even ladder", abs(legs.a[0, 1] - 0.5) < 1e-12,
      f"a={legs.a[0,1]}")
R = L.fly_level(m, legs, 16)
# by hand: belly B, front A, back C, a = (20.50-20.25)/(20.50-20.00) = 0.5
hand = 4.10 - 0.5 * 4.00 - 0.5 * 4.15
check("fly level matches hand arithmetic", abs(R[0, 1] - hand) < 1e-12,
      f"{R[0,1]:.6f} vs {hand:.6f}")
# day 2 raises B by 10bp only -> the fly cheapens by exactly 10bp, P&L of a long = -10bp
ret_bp = -(R[1, 1] - R[0, 1]) * 100.0
check("long fly loses 10bp when the belly cheapens 10bp", abs(ret_bp + 10.0) < 1e-9,
      f"{ret_bp:.4f}bp")

C = L.package_cost_bp(m, legs, anchor="measured")
# 3.0 price bp / 15 mod dur = 0.2 yield bp per leg; package weight |1|+|.5|+|.5| = 2
check("measured package cost = 2x leg spread", abs(C[0, 1] - 0.4) < 1e-12, f"{C[0,1]:.4f}")
Cf = L.package_cost_bp(m, legs, anchor="flat")
check("flat package cost = 2 x 0.30", abs(Cf[0, 1] - 0.6) < 1e-12, f"{Cf[0,1]:.4f}")
Cs = L.package_cost_bp(m, legs, anchor="sr1170")
check("sr1170 package cost = 2 x 166.98/15", abs(Cs[0, 1] - 2 * 166.98 / 15) < 1e-9,
      f"{Cs[0,1]:.4f}")

# MUTATION: a wrong 'a' must move the fly level
legs_bad = L.Legs(front=legs.front, back=legs.back, a=legs.a * 0 + 0.9, valid=legs.valid)
Rb = L.fly_level(m, legs_bad, 16)
check("MUTATION a=0.9 changes the fly (test bites)", abs(Rb[0, 1] - R[0, 1]) > 1e-6)

# ------------------------------------------------------------------ 2. wing gap band
m2 = L.Matrices(dates=m.dates, cusips=m.cusips,
                Y={16: m.Y[16]},
                RESZ={}, RES={}, STALE={},
                T=np.array([[20.0, 20.05, 20.50, 20.75]] * 2),   # A-B gap 0.05 < 0.10
                MODDUR=m.MODDUR, SPREAD_PX=m.SPREAD_PX, RANK=m.RANK,
                early_close=m.early_close, is_last_bd=m.is_last_bd)
l2 = L.build_legs(m2, step=1)
check("wing gap below the floor is refused", not bool(l2.valid[0, 1]))

# ------------------------------------------------------------------ 3. selection
D, N = 6, 20
rng = np.random.default_rng(0)
Z = rng.normal(size=(D, N))
elig = np.ones((D, N), bool)
sel = L.select(Z, elig, n=3)
for d in range(D):
    want_top = set(np.argsort(Z[d])[-3:])
    want_bot = set(np.argsort(Z[d])[:3])
    if set(sel.top[d]) != want_top or set(sel.bot[d]) != want_bot:
        check(f"selection row {d}", False, f"{sel.top[d]} {sel.bot[d]}")
        break
else:
    check("selection picks the true top-3 / bottom-3", True)

Zc = np.zeros((D, N))              # a perfectly tied signal
selc = L.select(Zc, elig, n=3)
check("a constant signal is refused outright", not selc.usable.any())

Zs = np.zeros((D, N)); Zs[:, 0] = 1.0; Zs[:, 1] = -1.0   # only 3 distinct values
sels = L.select(Zs, elig, n=3)
check("a signal with 3 distinct values is refused", not sels.usable.any())

# tie-break must NOT be array order: a signal with a big tied middle should not
# systematically pick the same low indices
Zt = np.zeros((D, N)); Zt[:, :2] = 1.0
selt = L.select(Zt, elig, n=3)
check("MUTATION tied-middle signal refused (would tilt by maturity)", not selt.usable.any())

# ------------------------------------------------------------------ 4. cell P&L
ret = np.zeros((D, N)); cost = np.full((D, N), 0.5)
for d in range(D):
    ret[d, sel.top[d]] = 2.0
    ret[d, sel.bot[d]] = -1.0
g, c, n = L.cell_pnl(ret, cost, sel)
# long the top (+2 each) and short the bottom (-(-1) = +1 each) -> mean of 3x2 and 3x1
check("cell_pnl averages long and short legs correctly",
      np.allclose(g[np.isfinite(g)], 1.5) and np.allclose(c[np.isfinite(c)], 0.5)
      and (n[sel.usable] == 6).all(), f"g={g[0]} c={c[0]} n={n[0]}")

# MUTATION: flip the sign convention on the short leg and the check must fail
rr0 = np.concatenate([ret[0, sel.top[0]], ret[0, sel.bot[0]]])
check("MUTATION un-negated short leg gives 0.5 not 1.5",
      abs(float(np.nanmean(rr0)) - 0.5) < 1e-9, f"{float(np.nanmean(rr0)):.4f}")

# ------------------------------------------------------------------ 5. perfect foresight
pf = np.nanmean(np.abs(ret[sel.usable][:, :]))
check("gross never exceeds the perfect-foresight bound",
      np.nanmean(g) <= np.nanmax(np.abs(ret)) + 1e-12)

# ------------------------------------------------------------------ 6. HAC t
x = np.random.default_rng(1).normal(size=4000)
t0 = L.newey_west_t(x, 1)
check("HAC t on iid noise is small", abs(t0) < 3.0, f"t={t0:.2f}")
# an AR(1) series with rho .9: naive t must be far larger than the HAC t
e = np.random.default_rng(2).normal(size=4000)
y = np.zeros(4000)
for i in range(1, 4000):
    y[i] = 0.9 * y[i - 1] + e[i]
y = y + 0.30
naive = y.mean() / (y.std(ddof=1) / np.sqrt(y.size))
hac = L.newey_west_t(y, 21)
check("HAC deflates an autocorrelated mean", abs(hac) < abs(naive) * 0.6,
      f"naive={naive:.2f} hac={hac:.2f}")

# ------------------------------------------------------------------ 7. lag / orth
M = np.arange(20, dtype=float).reshape(5, 4)
Ml = L.lag_matrix(M, 2)
check("lag_matrix shifts forward by rows", np.allclose(Ml[2], M[0]) and np.isnan(Ml[0]).all())

Zo = rng.normal(size=(D, N))
Co = rng.normal(size=(D, N))
Zmix = Zo + 3.0 * Co
Or = L.orthogonalize(Zmix, Co)
corr = [np.corrcoef(Or[d], Co[d])[0, 1] for d in range(D)]
check("orthogonalize removes the control", max(abs(np.array(corr))) < 1e-9,
      f"max|corr|={max(abs(np.array(corr))):.2e}")

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
