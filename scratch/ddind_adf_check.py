"""Validate indicator._adf against statsmodels on three series with known answers.

A stationarity meter that is itself wrong reports a drifting level as stable --
the exact failure the column exists to catch -- so it is checked against an
independent implementation before it is trusted on real flow.
"""
import numpy as np
from statsmodels.tsa.stattools import adfuller

from SDRUtils.dealer_direction import indicator as ind

rng = np.random.default_rng(101)
N = 1500

cases = {
    "white noise (stationary)": rng.normal(0, 1, N),
    "AR(1) phi=0.6 (stationary)": None,
    "AR(1) phi=0.98 (near unit root)": None,
    "random walk (non-stationary)": np.cumsum(rng.normal(0, 1, N)),
    "RW + drift (non-stationary)": np.cumsum(rng.normal(0.05, 1, N)),
}
for phi, name in ((0.6, "AR(1) phi=0.6 (stationary)"),
                  (0.98, "AR(1) phi=0.98 (near unit root)")):
    x = np.zeros(N)
    e = rng.normal(0, 1, N)
    for i in range(1, N):
        x[i] = phi * x[i - 1] + e[i]
    cases[name] = x

print(f"{'series':34s} {'ours':>9s} {'statsmodels':>12s} {'diff':>9s} "
      f"{'ours stat?':>11s} {'sm p<0.05?':>11s}")
worst = 0.0
for name, x in cases.items():
    t_ours, stat_ours = ind._adf(x)
    lags = int(min(25, max(1, np.ceil(12.0 * (len(x) / 100.0) ** 0.25))))
    t_sm, p_sm, *_ = adfuller(x, maxlag=lags, regression="c", autolag=None)
    worst = max(worst, abs(t_ours - t_sm))
    print(f"{name:34s} {t_ours:9.4f} {t_sm:12.4f} {t_ours - t_sm:9.2e} "
          f"{str(stat_ours):>11s} {str(bool(p_sm < 0.05)):>11s}")

print(f"\nworst |t_ours - t_statsmodels| = {worst:.3e}")
assert worst < 1e-8, "our ADF does not reproduce statsmodels"

# and the short-sample refusal
t, s = ind._adf(rng.normal(0, 1, ind.MIN_ADF_OBS - 1))
print(f"n = {ind.MIN_ADF_OBS - 1}: stationary = {s!r} (must be None, not True)")
assert s is None
print("PASS")
