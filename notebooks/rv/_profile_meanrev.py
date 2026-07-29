"""Profile the mean-reversion hot paths on the real panel, before optimising.

Reports measured wall-clock for the two things a sweep repeats thousands of
times: the rolling OU fit behind the S-score, and the rolling cointegrating
regression. Both had an obvious naive form; this is what replacing it bought.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

from RVUtils.MeanRev.signals import rolling_ols2_residual
from RVUtils.mean_reversion import calibrate_ou, rolling_ar1

DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"


def naive_rolling_ar1(s: pd.Series, window: int) -> pd.Series:
    """What ``ou_sscore(window=...)`` does today: re-fit from scratch per bar."""
    out = pd.Series(np.nan, index=s.index, dtype=float)
    w = int(window)
    for t in range(w, len(s) + 1):
        out.iloc[t - 1] = calibrate_ou(s.iloc[t - w:t])["half_life"]
    return out


def naive_rolling_ols2(y, x1, x2, window):
    """Per-bar lstsq instead of rolling cross-moments."""
    w = int(window)
    out = np.full(len(y), np.nan)
    Y, X1, X2 = y.to_numpy(), x1.to_numpy(), x2.to_numpy()
    for i in range(w - 1, len(Y)):
        sl = slice(i - w + 1, i + 1)
        A = np.column_stack([np.ones(w), X1[sl], X2[sl]])
        m = np.isfinite(A).all(axis=1) & np.isfinite(Y[sl])
        if m.sum() < w // 2:
            continue
        try:
            b = np.linalg.lstsq(A[m], Y[sl][m], rcond=None)[0]
        except Exception:
            continue
        out[i] = Y[i] - (b[0] + b[1] * X1[i] + b[2] * X2[i])
    return out


def main():
    st = pd.read_parquet(DATA / "structures_3m.parquet")
    st["as_of"] = pd.to_datetime(st["as_of"])
    lv = st.pivot_table(index="as_of", columns="key", values="value", aggfunc="first")
    keys = [c for c in lv.columns if lv[c].notna().sum() > 400][:26]
    lv = lv[keys]
    print(f"panel: {lv.shape[0]} bars x {lv.shape[1]} keys", flush=True)

    print("\n=== rolling AR(1) / OU fit, window 120 ===", flush=True)
    t0 = time.time()
    for c in keys:
        rolling_ar1(lv[c].dropna(), 120)
    fast = time.time() - t0
    print(f"  vectorised rolling_ar1 : {fast:8.3f}s  ({fast/len(keys)*1000:.1f} ms/key)",
          flush=True)

    sub = keys[:3]
    t0 = time.time()
    for c in sub:
        naive_rolling_ar1(lv[c].dropna(), 120)
    slow3 = time.time() - t0
    slow = slow3 / len(sub) * len(keys)
    print(f"  naive per-bar refit    : {slow:8.3f}s  (extrapolated from "
          f"{len(sub)} keys in {slow3:.1f}s)", flush=True)
    print(f"  --> speedup {slow / max(fast, 1e-9):.0f}x", flush=True)

    print("\n=== rolling cointegrating regression, window 252 ===", flush=True)
    g = st[st["key"] == keys[0]].sort_values("as_of")
    idx = pd.DatetimeIndex(g["as_of"])
    y = pd.Series(g["leg1_value"].to_numpy(float), index=idx)
    x1 = pd.Series(g["leg0_value"].to_numpy(float), index=idx)
    x2 = pd.Series(g["leg2_value"].to_numpy(float), index=idx)
    t0 = time.time()
    B = rolling_ols2_residual(y, x1, x2, 252)
    fast2 = time.time() - t0
    t0 = time.time()
    ref = naive_rolling_ols2(y, x1, x2, 252)
    slow2 = time.time() - t0
    both = np.isfinite(B["resid"].to_numpy()) & np.isfinite(ref)
    err = np.nanmax(np.abs(B["resid"].to_numpy()[both] - ref[both])) if both.any() else np.nan
    print(f"  rolling cross-moments  : {fast2:8.3f}s", flush=True)
    print(f"  naive per-bar lstsq    : {slow2:8.3f}s", flush=True)
    print(f"  --> speedup {slow2 / max(fast2, 1e-9):.1f}x, max |difference| {err:.2e}",
          flush=True)


if __name__ == "__main__":
    main()
