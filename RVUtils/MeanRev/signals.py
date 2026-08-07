"""Signal families: level panel (+ optional strip) -> signal panel.

Every function returns a wide ``date x key`` frame oriented so that **high means
rich** -- ``direction='fade'`` in the engine shorts a high signal. All of them
are causal: nothing uses a statistic that includes information after the bar the
signal is dated.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.mean_reversion import kalman_local_level, rolling_ar1, rolling_zscore

__all__ = [
    "zscore_signal", "bollinger_signal", "ou_sscore_signal", "kalman_level_signal",
    "xsection_signal", "pca_residual_signal", "curvefit_residual_signal",
    "coint_spread_signal", "rolling_ols2_residual", "structure_signal_from_slots",
    "meeting_residual_signal", "calendar_adjusted_signal", "scale_only_zscore",
]


# ---------------------------------------------------------------------------
# 1. z-score family
# ---------------------------------------------------------------------------

def zscore_signal(levels: pd.DataFrame, *, window: int = 120, ma: int = 1,
                  min_periods: Optional[int] = None, ddof: int = 0,
                  exclude_current: bool = False) -> pd.DataFrame:
    """Trailing z-score of an ``ma``-smoothed level, per key."""
    mp = min_periods if min_periods is not None else max(20, int(window) // 3)
    src = levels.rolling(int(ma)).mean() if int(ma) > 1 else levels
    return src.apply(lambda s: rolling_zscore(s, window, min_periods=mp, ddof=ddof,
                                              exclude_current=exclude_current))


def bollinger_signal(levels: pd.DataFrame, *, window: int = 60, ma_type: str = "sma",
                     min_periods: Optional[int] = None) -> pd.DataFrame:
    """Band-crossing signal: distance from the centre line in band widths.

    Identical algebra to a z-score; the difference that matters is the exit,
    which for a Bollinger rule is a touch of the centre line
    (``exit_style='band'`` with ``exit_z=0``), not a fixed horizon.
    ``ma_type='ema'`` uses an exponentially weighted centre and dispersion.
    """
    w = int(window)
    mp = min_periods if min_periods is not None else max(20, w // 3)
    if ma_type == "ema":
        mu = levels.ewm(span=w, min_periods=mp).mean()
        sd = levels.ewm(span=w, min_periods=mp).std()
    elif ma_type == "sma":
        r = levels.rolling(w, min_periods=mp)
        mu, sd = r.mean(), r.std(ddof=0)
    else:
        raise ValueError("ma_type must be 'sma' or 'ema'")
    return (levels - mu) / sd.where(sd > 1e-12)


# ---------------------------------------------------------------------------
# 2. OU / Kalman
# ---------------------------------------------------------------------------

def ou_sscore_signal(levels: pd.DataFrame, *, window: int = 120,
                     min_periods: Optional[int] = None) -> pd.DataFrame:
    """Avellaneda-Lee S-score from a rolling OU fit: ``(x - mu_t) / sigma_eq_t``.

    Differs from a plain z-score in that ``mu`` and the dispersion come from a
    fitted AR(1), so a slowly reverting series is not standardised as if its
    window mean were its equilibrium. NaN wherever the window is not
    mean-reverting -- which is a feature: those bars are not tradeable on an OU
    thesis and the engine will not enter.
    """
    mp = min_periods if min_periods is not None else int(window)
    out = {}
    for c in levels.columns:
        fit = rolling_ar1(levels[c], int(window), min_periods=mp)
        out[c] = (levels[c] - fit["mu"]) / fit["sigma_eq"].where(fit["sigma_eq"] > 1e-12)
    return pd.DataFrame(out, index=levels.index)


def kalman_level_signal(levels: pd.DataFrame, *, q: float = 1e-3, r: float = 1.0
                        ) -> pd.DataFrame:
    """Standardised innovation of a local-level Kalman filter.

    The fair value is formed from information through ``t-1``, so the signal is
    a genuine surprise rather than a deviation from a mean that already contains
    it. ``q/r`` sets the adaptation speed and is the only knob.
    """
    return pd.DataFrame({c: kalman_local_level(levels[c], q=q, r=r)["z"]
                         for c in levels.columns}, index=levels.index)


# ---------------------------------------------------------------------------
# 3. cross-sectional
# ---------------------------------------------------------------------------

def xsection_signal(levels: pd.DataFrame, *, groups: Optional[pd.Series] = None,
                    method: str = "zscore", window: Optional[int] = None,
                    min_names: int = 3) -> pd.DataFrame:
    """Standardise across keys **within a date**, optionally within a bucket.

    Cross-gap scale differs by an order of magnitude between a 3m and a 12m fly,
    so pooling raw levels ranks maturity, not richness. ``groups`` maps key ->
    bucket; standardisation happens inside each bucket and the result is
    comparable across them (the ``kink_fade`` house pattern).

    ``window`` first converts each key to its own trailing z-score, so the
    cross-section ranks *dislocation* rather than *level* -- a fly can be
    structurally the highest in its bucket forever without ever being rich.
    """
    # ``window`` arrives from a grid, where a None sits in a numeric column and
    # becomes NaN. Treat any non-positive/NaN value as "rank the raw level".
    src = levels
    if window is not None and np.isfinite(window) and int(window) > 0:
        src = zscore_signal(levels, window=int(window))
    if groups is None:
        g = pd.Series("all", index=src.columns)
    else:
        g = pd.Series(groups).reindex(src.columns)
        g = g.fillna("all")
    out = pd.DataFrame(np.nan, index=src.index, columns=src.columns)
    for bucket, cols in g.groupby(g):
        sub = src[list(cols.index)]
        n = sub.notna().sum(axis=1)
        if method == "rank":
            # Normal scores, not raw rank percentiles. A (pct - 0.5) * 2 signal
            # is bounded by +/-1, so any entry threshold above 1 can never fire
            # and the whole method drops out of a shared grid with zero trades.
            # The inverse normal CDF puts ranks on the same scale as a z-score.
            from scipy.stats import norm

            r = sub.rank(axis=1, pct=True)
            nn = sub.notna().sum(axis=1)
            r = r.mul(nn, axis=0).sub(0.5).div(nn, axis=0)   # (i - 0.5)/n
            z = pd.DataFrame(norm.ppf(r.clip(1e-6, 1 - 1e-6).to_numpy()),
                             index=r.index, columns=r.columns).where(r.notna())
        elif method == "zscore":
            mu = sub.mean(axis=1)
            sd = sub.std(axis=1, ddof=0)
            z = sub.sub(mu, axis=0).div(sd.where(sd > 1e-12), axis=0)
        else:
            raise ValueError("method must be 'zscore' or 'rank'")
        out.loc[:, list(cols.index)] = z.where(n >= min_names, np.nan)
    return out


# ---------------------------------------------------------------------------
# 4. curve-model residuals (strip -> per-slot residual -> structure)
# ---------------------------------------------------------------------------

def structure_signal_from_slots(
    slot_resid: pd.DataFrame, struct: pd.DataFrame, *, n_legs: int = 3,
    weights: Sequence[float] = (-1.0, 2.0, -1.0), scale: float = 100.0,
    date_col: str = "as_of",
) -> pd.DataFrame:
    """Combine a per-slot residual panel into a per-structure signal panel.

    ``slot_resid`` is ``date x slot``; ``struct`` is the long structure frame
    carrying ``leg{j}_slot``. The structure's residual is the same weighted sum
    of its legs' residuals as its level is of its legs' rates, so the units
    match the traded object (bp).
    """
    s = struct.copy()
    s[date_col] = pd.to_datetime(s[date_col])
    resid = slot_resid.copy()
    resid.index = pd.to_datetime(resid.index)
    total = None
    for j in range(n_legs):
        lookup = resid.stack(future_stack=True).rename("r").reset_index()
        lookup.columns = [date_col, f"leg{j}_slot", "r"]
        merged = s[[date_col, "key", f"leg{j}_slot"]].merge(
            lookup, on=[date_col, f"leg{j}_slot"], how="left")
        term = float(weights[j]) * merged["r"].to_numpy()
        total = term if total is None else total + term
    s["signal"] = total * float(scale)
    return s.pivot_table(index=date_col, columns="key", values="signal",
                         aggfunc="first").sort_index()


def pca_residual_signal(
    slot_panel: pd.DataFrame, struct: pd.DataFrame, *, window: int = 261,
    k: int = 3, on: str = "levels", n_legs: int = 3,
    weights: Sequence[float] = (-1.0, 2.0, -1.0), scale: float = 100.0,
    min_periods: Optional[int] = None, date_col: str = "as_of",
) -> pd.DataFrame:
    """Rolling-PCA residual of the strip, mapped onto structures.

    One eigendecomposition **per date** on the ``date x slot`` panel (not one
    per structure), reconstructing each date's cross-section from its ``k``
    leading trailing-window factors. Per-structure rolling PCA would repeat the
    same decomposition once per fly; on a 16-slot strip with 26 structures that
    is 26x the work for identical residuals.

    Loadings are sign-aligned to the previous window so a spontaneous
    eigenvector flip does not print as a residual jump.
    """
    P = slot_panel.dropna(axis=1, how="all").sort_index()
    cols = list(P.columns)
    X = P[cols].to_numpy(dtype=float)
    n, m = X.shape
    w = int(window)
    mp = int(min_periods) if min_periods is not None else w
    resid = np.full((n, m), np.nan)
    prev_V = None
    for i in range(n):
        lo = max(0, i - w + 1)
        blk = X[lo:i + 1]
        blk = blk[np.isfinite(blk).all(axis=1)]
        if blk.shape[0] < mp:
            continue
        src = np.diff(blk, axis=0) if on == "changes" else blk
        if src.shape[0] < 3:
            continue
        mu = src.mean(axis=0)
        C = np.cov(src - mu, rowvar=False)
        try:
            vals, V = np.linalg.eigh(C)
        except np.linalg.LinAlgError:
            continue
        order = np.argsort(vals)[::-1]
        V = V[:, order][:, :int(k)]
        if prev_V is not None and prev_V.shape == V.shape:
            flip = np.sign(np.sum(V * prev_V, axis=0))
            flip[flip == 0] = 1.0
            V = V * flip
        prev_V = V
        x = X[i]
        if not np.isfinite(x).all():
            continue
        base = blk.mean(axis=0) if on == "changes" else mu
        y = x - base
        resid[i] = y - V @ (V.T @ y)
    R = pd.DataFrame(resid, index=P.index, columns=cols)
    return structure_signal_from_slots(R, struct, n_legs=n_legs, weights=weights,
                                       scale=scale, date_col=date_col)


def curvefit_residual_signal(
    slot_panel: pd.DataFrame, struct: pd.DataFrame, *, form: str = "nss",
    n_legs: int = 3, weights: Sequence[float] = (-1.0, 2.0, -1.0),
    scale: float = 100.0, date_col: str = "as_of",
    quarters_per_year: float = 4.0,
) -> pd.DataFrame:
    """Residual of each date's strip from a smooth fitted curve.

    ``form`` is ``'ns'``, ``'nss'`` (Nelson-Siegel / Svensson, sharing the
    functional forms in :mod:`RVUtils.curve_fit_rv`), ``'spline'`` (cubic
    least-squares spline) or ``'poly3'``. The fit is **cross-sectional on that
    date only**, so it carries no time-series look-ahead by construction.

    A butterfly is already a second difference along the strip, so it is close
    to orthogonal to any smooth fit -- which is exactly why the residual of a
    smooth fit is a fly-shaped object and worth trading against.
    """
    from RVUtils.curve_fit_rv import _ns_yield, _nss_yield

    P = slot_panel.dropna(axis=1, how="all").sort_index()
    cols = list(P.columns)
    x = np.array([float(c) / float(quarters_per_year) for c in cols])
    out = np.full((len(P), len(cols)), np.nan)
    arr = P[cols].to_numpy(dtype=float)
    # Warm start: the strip barely moves day to day, so seeding each fit with
    # yesterday's parameters cuts the Levenberg-Marquardt iteration count by an
    # order of magnitude versus re-seeding from a fixed guess every date.
    warm = None

    for i in range(arr.shape[0]):
        y = arr[i]
        ok = np.isfinite(y)
        if ok.sum() < 6:
            continue
        xf, yf = x[ok], y[ok]
        try:
            if form in ("ns", "nss"):
                from scipy.optimize import least_squares

                fn = _ns_yield if form == "ns" else _nss_yield
                cold = ([yf[-1], yf[0] - yf[-1], 0.0, 2.0] if form == "ns"
                        else [yf[-1], yf[0] - yf[-1], 0.0, 0.0, 2.0, 5.0])
                p0 = warm if warm is not None and len(warm) == len(cold) else cold
                # The optimiser probes extreme decay parameters, where the
                # NS/NSS basis functions overflow; that is the search working,
                # not a data problem, so it is not worth a warning per date.
                with np.errstate(over="ignore", invalid="ignore"):
                    res = least_squares(lambda p: fn(xf, *p) - yf, p0,
                                        max_nfev=200)
                    if not res.success:
                        res = least_squares(lambda p: fn(xf, *p) - yf, cold,
                                            max_nfev=800)
                    warm = res.x if res.success else None
                    fit_all = fn(x, *res.x)
            elif form == "spline":
                from scipy.interpolate import LSQUnivariateSpline

                knots = np.quantile(xf, [0.33, 0.66])
                sp = LSQUnivariateSpline(xf, yf, t=knots, k=3)
                fit_all = sp(x)
            elif form == "poly3":
                fit_all = np.polyval(np.polyfit(xf, yf, 3), x)
            else:
                raise ValueError("form must be 'ns', 'nss', 'spline' or 'poly3'")
        except Exception:
            continue
        out[i] = y - fit_all
    R = pd.DataFrame(out, index=P.index, columns=cols)
    return structure_signal_from_slots(R, struct, n_legs=n_legs, weights=weights,
                                       scale=scale, date_col=date_col)


# ---------------------------------------------------------------------------
# 4b. meeting-calendar residuals
# ---------------------------------------------------------------------------

def scale_only_zscore(levels: pd.DataFrame, *, window: int = 120,
                      min_periods: Optional[int] = None) -> pd.DataFrame:
    """``x / rolling_sd(x)`` -- standardise the scale, do **not** re-centre.

    For a series that is already a deviation from a fitted fair value, a plain
    z-score subtracts a *trailing window mean* of that deviation and so throws
    away the model's own zero. If the model is any good, zero is the right
    anchor and the only thing left to estimate is how far from it counts as far.

    Keeping both this and :func:`zscore_signal` in the grid makes "does the
    model's zero beat a trailing mean?" a measurement rather than a choice.
    """
    w = int(window)
    mp = min_periods if min_periods is not None else max(20, w // 3)
    sd = levels.rolling(w, min_periods=mp).std(ddof=0)
    return levels / sd.where(sd > 1e-12)


def meeting_residual_signal(
    levels: pd.DataFrame, *, resid_panel: pd.DataFrame, struct: pd.DataFrame,
    window: int = 120, standardise: str = "scale", n_legs: int = 3,
    weights: Sequence[float] = (-1.0, 2.0, -1.0), date_col: str = "as_of",
    min_periods: Optional[int] = None,
) -> pd.DataFrame:
    """Butterfly of the per-contract residual from a smooth **policy path**.

    ``resid_panel`` is the ``date x slot`` residual from
    :func:`RVUtils.MeanRev.meetings.meeting_residual_panel`, already in bp. It
    is combined into structures with the same weights the level uses, so the
    signal is in bp of the traded object and directly comparable to the fly
    itself.

    This is the whole thesis of the kink lab in one function. A butterfly on
    three consecutive SR3 contracts is not a clean curvature measure, because
    each contract settles on a day-weighted average over its own IMM quarter and
    the FOMC calendar is lumpy against the IMM grid. Removing the fly that a
    *smooth policy path* would print leaves the curvature the calendar cannot
    explain -- which is the only part there was ever any reason to fade.

    ``standardise`` is ``'scale'`` (divide by a trailing sd, keep the model's
    zero -- see :func:`scale_only_zscore`), ``'z'`` (full trailing z-score) or
    ``'raw'`` (bp, for a threshold expressed in bp).

    ``levels`` is accepted and unused so the signature matches the grid-search
    contract; the residual panel is the input that matters.
    """
    sig_bp = structure_signal_from_slots(resid_panel, struct, n_legs=n_legs,
                                         weights=weights, scale=1.0,
                                         date_col=date_col)
    sig_bp = sig_bp.reindex(index=levels.index, columns=levels.columns)
    return _standardise(sig_bp, standardise, window, min_periods)


def _standardise(panel: pd.DataFrame, how: str, window: int,
                 min_periods: Optional[int]) -> pd.DataFrame:
    if how == "raw":
        return panel
    if how == "scale":
        return scale_only_zscore(panel, window=window, min_periods=min_periods)
    if how == "z":
        return zscore_signal(panel, window=window, min_periods=min_periods)
    raise ValueError("standardise must be 'scale', 'z' or 'raw'")


def calendar_adjusted_signal(
    levels: pd.DataFrame, *, adjusted: pd.DataFrame, window: int = 120,
    standardise: str = "scale", min_periods: Optional[int] = None,
) -> pd.DataFrame:
    """Standardise an already calendar-adjusted level panel.

    ``adjusted`` is normally
    :func:`RVUtils.MeanRev.meetings.calendar_tilted_fly`'s ``'level'`` -- the
    butterfly with the fly a **locally uniform** policy path would print removed,
    using nothing but the structure's own two wings and the meeting calendar.

    This is the one-degree-of-freedom cousin of
    :func:`meeting_residual_signal`: it removes the first-order calendar effect
    without fitting a jump per meeting, so it cannot overfit and it is trivial to
    explain to a desk. If the full per-meeting fit does not beat it, the extra
    machinery is not earning anything.

    ``levels`` fixes the output's index and columns and is otherwise unused, so
    the signature matches the grid-search contract.
    """
    adj = adjusted.reindex(index=levels.index, columns=levels.columns)
    return _standardise(adj, standardise, window, min_periods)


# ---------------------------------------------------------------------------
# 5. cointegration
# ---------------------------------------------------------------------------

def rolling_ols2_residual(y: pd.Series, x1: pd.Series, x2: pd.Series,
                          window: int, *, min_periods: Optional[int] = None
                          ) -> pd.DataFrame:
    """Trailing OLS of ``y`` on ``[1, x1, x2]``; residual at each bar.

    This is Engle-Granger step 1 with a rolling estimation window: the fitted
    coefficients are the empirical cointegrating vector, against which the
    asserted ``1/-2/1`` is the null. Solved from rolling cross-moments, so the
    cost is one 3x3 solve per bar rather than a regression per bar.
    """
    w = int(window)
    mp = int(min_periods) if min_periods is not None else w
    df = pd.DataFrame({"y": y, "x1": x1, "x2": x2}).astype(float)
    ok = df.notna().all(axis=1)
    d = df.where(ok)
    one = ok.astype(float)
    r = lambda s: s.fillna(0.0).rolling(w, min_periods=1).sum()      # noqa: E731
    names = ["1", "x1", "x2"]
    vecs = {"1": one.where(ok), "x1": d["x1"], "x2": d["x2"]}
    # Materialise the rolling cross-moments as numpy up front. Indexing nine
    # pandas Series with .iloc inside the per-bar loop was ~40x the cost of the
    # 3x3 solve itself.
    n = one.rolling(w, min_periods=1).sum().to_numpy()
    S = np.empty((len(df), 3, 3))
    rhs_all = np.empty((len(df), 3))
    for ia, a in enumerate(names):
        for ib, b in enumerate(names):
            S[:, ia, ib] = r(vecs[a] * vecs[b]).to_numpy()
        rhs_all[:, ia] = r(vecs[a] * d["y"]).to_numpy()
    idx = df.index
    beta = np.full((len(idx), 3), np.nan)
    for i in range(len(idx)):
        if n[i] < mp:
            continue
        try:
            beta[i] = np.linalg.solve(S[i], rhs_all[i])
        except np.linalg.LinAlgError:
            continue
    B = pd.DataFrame(beta, index=idx, columns=["const", "b1", "b2"])
    fitted = B["const"] + B["b1"] * df["x1"] + B["b2"] * df["x2"]
    B["resid"] = df["y"] - fitted
    return B


def coint_spread_signal(
    struct: pd.DataFrame, *, window: int = 252, z_window: int = 120,
    date_col: str = "as_of", n_legs: int = 3, scale: float = 100.0,
    min_periods: Optional[int] = None,
) -> Dict[str, pd.DataFrame]:
    """Fitted-vector (Engle-Granger) spread and its z-score, per structure.

    Regresses the belly on the two wings over a trailing window and z-scores the
    residual. Returns ``{'signal', 'spread', 'b1', 'b2'}`` so the fitted hedge
    ratios can be compared against the asserted ``(0.5, 0.5)`` that ``1/-2/1``
    implies -- if the fitted vector is far from that, the traded fly is not the
    cointegrating combination.
    """
    sig, spr, b1s, b2s = {}, {}, {}, {}
    for key, g in struct.groupby("key"):
        g = g.sort_values(date_col)
        idx = pd.DatetimeIndex(pd.to_datetime(g[date_col]))
        if len(g) < max(int(window), 30):
            continue
        y = pd.Series(g["leg1_value"].to_numpy(dtype=float), index=idx)
        x1 = pd.Series(g["leg0_value"].to_numpy(dtype=float), index=idx)
        x2 = pd.Series(g[f"leg{n_legs-1}_value"].to_numpy(dtype=float), index=idx)
        B = rolling_ols2_residual(y, x1, x2, window, min_periods=min_periods)
        s = B["resid"] * float(scale)
        spr[key] = s
        b1s[key] = B["b1"]
        b2s[key] = B["b2"]
        sig[key] = rolling_zscore(s, int(z_window),
                                  min_periods=max(20, int(z_window) // 3))
    return {"signal": pd.DataFrame(sig).sort_index(),
            "spread": pd.DataFrame(spr).sort_index(),
            "b1": pd.DataFrame(b1s).sort_index(),
            "b2": pd.DataFrame(b2s).sort_index()}
