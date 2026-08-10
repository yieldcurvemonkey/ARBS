"""Regressing the mid change on the multi-level order-flow vector.

The estimation choice here is not stylistic.  Xu, Gould and Howison measure
pairwise correlations between MLOFI components staying **above 0.5 even between
level 1 and level 10**, and above 0.7 for every pair on their large-tick names,
with the eigenvalue ratio of the design matrix collapsing to zero beyond the first
component.  Under OLS the individual coefficients are then mostly insignificant --
their AMZN level-5 coefficient is 1.13 with a standard error of 2.33 -- and the
out-of-sample error actually *rises* beyond about five levels.  Under Ridge nearly
all coefficients become strongly significant and the error is monotone decreasing
in the number of levels.

So this module fits Ridge by default, picks the penalty by cross-validation over a
log-spaced grid as they do, and reports the OLS fit beside it rather than instead
of it -- because the gap between the two is the diagnostic that tells you the
collinearity is real.

The reason to bother, on this data specifically: their improvement is **65 to 75
per cent for large-tick instruments** against 15 to 30 per cent for small-tick
ones, and every contract in this archive is large-tick -- the spread is one tick
almost always.  Both degeneracies that cap the small-tick case need a spread wider
than one tick and so cannot arise here.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd

__all__ = ["mlofi_bars", "mlofi_regression", "ofi_bar_scan"]


def mlofi_bars(frame: pd.DataFrame, freq: str = "10s") -> pd.DataFrame:
    """Sum the per-event level vector into bars, with the bar-to-bar mid change.

    ``d_mid`` is the change between consecutive bars' closing mids, forward-filled
    through empty bars -- not the within-bar move. A bar in which nothing happened
    saw no price change, and taking the within-bar range would score its own
    activity rather than the market's.

    Pass a ``date`` column when the frame spans more than one session, and the
    difference is taken within each. Without one the whole frame is treated as a
    single session, which is what :func:`RVUtils.MBO.mlofi.replay_mlofi` returns.
    """
    e_cols = [c for c in frame.columns if c.startswith("e_")]
    if frame.empty or not e_cols:
        return pd.DataFrame(columns=["n_events", "mid_last", "d_mid"] + e_cols)

    t = frame.set_index("ts_recv").sort_index()
    agg = {c: (c, "sum") for c in e_cols}
    agg["n_events"] = ("mid", "size")
    agg["mid_last"] = ("mid", "last")

    # **Difference within a session, never across one.**  Forward-filling and
    # differencing a concatenated frame charges the whole overnight gap to the
    # first bar of the next session, and resampling across the gap manufactures a
    # bar for every empty interval in between: measured on two sessions 24 hours
    # apart, 8,642 bars of which 99.95% carry no flow and no price change, with
    # the entire overnight move loaded onto one of them.
    if "date" in frame.columns:
        parts = []
        for _, g in t.groupby(t["date"], sort=True):
            b = g.resample(freq).agg(**agg)
            b = b[b["n_events"].gt(0) | b["mid_last"].notna()
                  | (b.index >= g.index.min()) & (b.index <= g.index.max())]
            b["d_mid"] = b["mid_last"].ffill().diff()
            parts.append(b)
        bars = pd.concat(parts).sort_index() if parts else t.resample(freq).agg(**agg)
        return bars
    bars = t.resample(freq).agg(**agg)
    bars["d_mid"] = bars["mid_last"].ffill().diff()
    return bars


def _ridge(x: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    """Ridge coefficients with an unpenalised intercept.

    Solved by least squares rather than by ``solve``, because at ``lam = 0`` the
    normal equations here are **singular in the ordinary case, not the pathological
    one**.  Xu, Gould and Howison measure the eigenvalue ratio of exactly this
    design matrix collapsing to zero beyond the first component, with every pair of
    levels correlated above 0.7 on large-tick names -- which is what makes the
    penalty necessary in the first place.  A solver that raises on the unpenalised
    comparison fit would refuse to compute the very baseline the penalty is
    supposed to beat.  ``lstsq`` returns the minimum-norm solution instead, which
    is the right answer for a rank-deficient design.
    """
    xm, ym = x.mean(axis=0), y.mean()
    # **Standardise before penalising.**  Ridge shrinks in the units of the design,
    # so on an unstandardised matrix the penalty means something different for
    # every instrument -- and here it silently means nothing at all.  These columns
    # are order flow in LOTS: ZT rests three thousand at the touch, so the entries
    # of X'X run to 1e11 and a penalty of 1e5 is a rounding error. Measured before
    # this fix, cross-validation picked the largest lambda on the grid for every
    # single fit and the Ridge and OLS errors agreed to four decimals -- the
    # penalty was inert, and the Ridge-versus-OLS gap that is supposed to diagnose
    # collinearity was vacuous.  Scaling to unit variance makes lambda comparable
    # across instruments and across levels, which is the only way the fitted value
    # means anything.
    sd = x.std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    xc, yc = (x - xm) / sd, y - ym
    p = xc.shape[1]
    a = xc.T @ xc + lam * np.eye(p)
    beta_s, *_ = np.linalg.lstsq(a, xc.T @ yc, rcond=None)
    beta = beta_s / sd
    return np.concatenate([[ym - xm @ beta], beta])


def _fit_predict(x, beta):
    return beta[0] + x @ beta[1:]


def mlofi_regression(
    bars: pd.DataFrame,
    levels: Optional[int] = None,
    lambdas: Optional[Sequence[float]] = None,
    n_folds: int = 5,
    tick: Optional[float] = None,
) -> dict:
    """Fit the mid change on the level vector, by Ridge and by OLS.

    Returns both fits and their out-of-sample errors, because the gap between them
    is the evidence that the components are collinear enough to need the penalty.
    ``rmse_1`` is the touch-only fit, so ``improvement`` answers the question the
    whole exercise is about: what did the deeper book buy?

    Cross-validation folds are contiguous blocks in time, never random: bars are
    serially dependent and a shuffled fold leaks a bar's neighbours into the
    training set, which flatters the out-of-sample error.
    """
    e_cols = [c for c in bars.columns if c.startswith("e_")]
    if levels is not None:
        e_cols = e_cols[: int(levels)]
    v = bars.dropna(subset=["d_mid"] + e_cols)
    n = len(v)
    out = {"n_bars": int(n), "levels": len(e_cols)}
    if n < 30 or not e_cols:
        return {**out, "lambda": np.nan, "rmse_ridge": np.nan, "rmse_ols": np.nan,
                "rmse_1": np.nan, "improvement": np.nan, "r2_ridge": np.nan,
                "beta_ridge": []}

    x = v[e_cols].to_numpy(dtype=np.float64)
    y = v["d_mid"].to_numpy(dtype=np.float64)
    if tick:
        y = y / float(tick)

    if lambdas is None:
        # Wide enough that the optimum is interior. If the fitted lambda
        # lands on an endpoint the grid was too narrow and the number is
        # not an optimum -- 'lambda_at_bound' below says when that happens.
        lambdas = np.logspace(-6, 8, 60)

    folds = np.array_split(np.arange(n), max(2, int(n_folds)))

    def cv_rmse(cols_x, lam):
        errs = []
        for f in folds:
            mask = np.ones(n, dtype=bool)
            mask[f] = False
            if mask.sum() < len(cols_x[0]) + 2:
                continue
            b = _ridge(cols_x[mask], y[mask], lam)
            errs.append(y[f] - _fit_predict(cols_x[f], b))
        if not errs:
            return np.nan
        e = np.concatenate(errs)
        return float(np.sqrt(np.mean(e * e)))

    scores = [(lam, cv_rmse(x, lam)) for lam in lambdas]
    scores = [(l, s) for l, s in scores if np.isfinite(s)]
    best_lam = min(scores, key=lambda t: t[1])[0] if scores else np.nan
    rmse_ridge = min(s for _, s in scores) if scores else np.nan
    rmse_ols = cv_rmse(x, 0.0)
    rmse_1 = cv_rmse(x[:, :1], 0.0)

    beta = _ridge(x, y, best_lam if np.isfinite(best_lam) else 0.0)
    resid = y - _fit_predict(x, beta)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = float(1.0 - (resid @ resid) / ss_tot) if ss_tot > 0 else np.nan

    return {
        **out,
        "lambda": float(best_lam),
        # A fitted penalty sitting on the edge of the search grid is not a chosen
        # value, it is a clipped one, and the fit should not be read as tuned.
        "lambda_at_bound": bool(
            np.isfinite(best_lam)
            and (best_lam <= min(lambdas) * 1.0001 or best_lam >= max(lambdas) * 0.9999)
        ),
        "rmse_ridge": rmse_ridge,
        "rmse_ols": rmse_ols,
        "rmse_1": rmse_1,
        # Positive means the deeper book reduced out-of-sample error.
        "improvement": (float(1.0 - rmse_ridge / rmse_1)
                        if np.isfinite(rmse_1) and rmse_1 > 0 else np.nan),
        "r2_ridge": r2,
        "beta_ridge": [float(b) for b in beta[1:]],
    }


def ofi_bar_scan(tob: pd.DataFrame,
                 freqs: Sequence[str] = ("1s", "10s", "60s", "300s", "900s"),
                 ) -> pd.DataFrame:
    """Touch-OFI correlation against bar length, and the share of pinned bars.

    The diagnostic that explains an apparently broken instrument.  ZT's touch OFI
    correlates -0.107 with the same-second mid change and only reaches 0.410 at a
    minute: it has the finest tick of the complex and 3,086 lots at the touch, so
    its front queue turns over enormously without the price moving.  Nothing is
    wrong with it -- the default bar is simply too short for the deepest book, and
    ``zero_frac`` shows why, by reporting how many bars had no mid change at all
    for the correlation to explain.
    """
    from RVUtils.MBO.analytics.flow import ofi_bars

    rows = []
    for f in freqs:
        b = ofi_bars(tob, freq=f)
        v = b.dropna(subset=["ofi", "d_mid"])
        if len(v) < 30:
            rows.append({"freq": f, "n_bars": int(len(v)), "corr": np.nan,
                         "zero_frac": np.nan})
            continue
        rows.append({
            "freq": f,
            "n_bars": int(len(v)),
            "corr": float(np.corrcoef(v["ofi"], v["d_mid"])[0, 1]),
            "zero_frac": float((v["d_mid"] == 0).mean()),
        })
    return pd.DataFrame(rows)
