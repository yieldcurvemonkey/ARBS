"""The local fitted curve, and the per-bond richness residual it defines.

Why a LOCAL fit rather than the repo's whole-curve spline
---------------------------------------------------------
``FixedRateBondValue.SPLINE_SPREAD`` fits the entire 1-30y curve and reports each bond's
error against it. That is the right object for "is the 7-year sector cheap". It is the
wrong one here, because a whole-curve spline has only a handful of knots past twenty
years and its residual in that region is dominated by the shape it could not bend to,
not by the individual bond. This study lives inside a ten-year window where forty
CUSIPs sit three months apart, so the fit has to be local to that window to leave a
residual that is about the *bond*.

The coupon effect is fitted, not ignored
----------------------------------------
Two Treasuries maturing in the same month can carry coupons of 1.25% and 5.0% -- the
20-30y band spans exactly that, because it holds bonds issued across a full rate cycle.
At equal maturity the low-coupon bond has the longer duration and, in any non-flat
curve, a different yield to maturity for reasons that have nothing to do with richness.
Fitting ``y ~ poly(x, deg)`` alone therefore books a systematic residual that is really
a coupon, and it is *persistent*, which is worse: a signal ranked on it would hold the
same names for years and call it alpha.

Two independent handles on this, both exposed:

* ``x_axis="mod_dur"`` fits in duration space, which absorbs most of the effect because
  duration is where the coupon shows up; and
* ``include_coupon=True`` adds the coupon as a linear regressor, which absorbs the rest.

Neither is free -- a coupon regressor can soak up genuine cheapness that happens to
correlate with vintage -- so both are config knobs and the notebook shows the residual
with and without.

Fit robustly, or the outlier defines the curve
-----------------------------------------------
The point of the residual is to find the bond that is out of line; ordinary least
squares moves the curve toward that bond and shrinks the very number being measured.
The default is therefore an iteratively re-weighted (Huber) fit, so one dislocated issue
in forty is measured against the other thirty-nine rather than partly against itself.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd


def _design(x: np.ndarray, deg: int, cpn: Optional[np.ndarray]) -> np.ndarray:
    cols = [np.ones_like(x)] + [x ** k for k in range(1, deg + 1)]
    if cpn is not None:
        cols.append(cpn)
    return np.column_stack(cols)


def _huber_fit(A: np.ndarray, y: np.ndarray, *, iters: int = 6, c: float = 1.5) -> np.ndarray:
    """IRLS with a Huber weight. Falls back to OLS if the scale collapses."""
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    for _ in range(iters):
        r = y - A @ beta
        s = 1.4826 * np.median(np.abs(r - np.median(r)))
        if not np.isfinite(s) or s <= 1e-12:
            break
        u = np.abs(r) / (c * s)
        w = np.where(u <= 1.0, 1.0, 1.0 / np.maximum(u, 1e-9))
        Aw, yw = A * w[:, None], y * w
        try:
            beta, *_ = np.linalg.lstsq(Aw, yw, rcond=None)
        except np.linalg.LinAlgError:
            break
    return beta


def fit_residuals(
    df: pd.DataFrame,
    *,
    deg: int = 3,
    x_axis: str = "ttm",
    include_coupon: bool = True,
    robust: bool = True,
    min_bonds: int = 12,
    y_col: str = "ytm",
) -> pd.DataFrame:
    """Add ``fit``, ``resid_bp`` and ``fit_rmse_bp`` per date.

    ``resid_bp > 0`` means the bond yields MORE than the local curve says it should --
    it is **cheap**. Buying a cheap bond is betting the residual falls, so the sign
    convention downstream is: a positive residual is a positive reason to buy.
    """
    if x_axis not in ("ttm", "mod_dur"):
        raise ValueError(f"x_axis must be 'ttm' or 'mod_dur', got {x_axis!r}")

    out = []
    for d, g in df.groupby("date", sort=True):
        g = g.dropna(subset=[y_col, x_axis]).copy()
        if len(g) < min_bonds:
            g["fit"] = np.nan
            g["resid_bp"] = np.nan
            g["fit_rmse_bp"] = np.nan
            out.append(g)
            continue
        x = g[x_axis].to_numpy(float)
        # Centre and scale: a raw ttm^3 over a 20-30 window makes the design matrix
        # badly conditioned and the fitted curve wobble in a way that reads as richness.
        xs = (x - x.mean()) / max(1e-9, x.std())
        y = g[y_col].to_numpy(float)
        cpn = g["cpn"].to_numpy(float) if (include_coupon and "cpn" in g.columns) else None
        A = _design(xs, deg, cpn)
        beta = _huber_fit(A, y) if robust else np.linalg.lstsq(A, y, rcond=None)[0]
        fit = A @ beta
        g["fit"] = fit
        g["resid_bp"] = (y - fit) * 100.0
        g["fit_rmse_bp"] = float(np.sqrt(np.mean((y - fit) ** 2)) * 100.0)
        out.append(g)
    return pd.concat(out, ignore_index=True) if out else df.assign(
        fit=np.nan, resid_bp=np.nan, fit_rmse_bp=np.nan)


def residual_quality(panel: pd.DataFrame) -> pd.DataFrame:
    """QC on the residual series before anything is traded on it.

    Lag-1 autocorrelation is the metric that matters. A genuine per-bond richness
    residual is highly persistent -- a bond does not become cheap and rich again
    overnight -- so a real series runs 0.85-0.99. Near zero means the residual is
    dominated by pricing noise, and a mean-reversion signal fitted to noise reverts
    beautifully in sample and pays the spread out of sample.

    This is the check that caught a wrong-root QuantLib yield turning a rank spread from
    ``sd 0.86bp, autocorr +0.92`` into ``sd 18.9bp, autocorr +0.01``.
    """
    piv = panel.pivot_table(index="date", columns="cusip", values="resid_bp").sort_index()
    ac1 = piv.apply(lambda c: c.dropna().autocorr(1))
    ac5 = piv.apply(lambda c: c.dropna().autocorr(5))
    sd = piv.std()
    n = piv.notna().sum()
    return pd.DataFrame({"autocorr_1": ac1, "autocorr_5": ac5,
                         "sd_bp": sd, "n_obs": n}).dropna(subset=["autocorr_1"])


def half_life_days(panel: pd.DataFrame, *, min_obs: int = 250) -> pd.Series:
    """Per-CUSIP OU half-life of the richness residual, in business days.

    The horizon knob in the backtest is otherwise pure search. This gives it a
    measured prior: a signal held far past the residual's own half-life is paying
    carry and spread to hold a position whose thesis has already played out.
    """
    piv = panel.pivot_table(index="date", columns="cusip", values="resid_bp").sort_index()
    out = {}
    for c in piv.columns:
        s = piv[c].dropna()
        if len(s) < min_obs:
            continue
        x, y = s.iloc[:-1].to_numpy(float), s.diff().dropna().to_numpy(float)
        xc = x - x.mean()
        denom = float(np.dot(xc, xc))
        if denom <= 0:
            continue
        b = float(np.dot(xc, y - y.mean()) / denom)
        if b >= 0:                       # not mean reverting
            out[c] = np.inf
        else:
            out[c] = float(np.log(2.0) / -np.log1p(b)) if b > -1 else 0.0
    return pd.Series(out, name="half_life_days")
