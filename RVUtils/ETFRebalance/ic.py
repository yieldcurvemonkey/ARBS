"""Information coefficients: does any of this predict anything, and over what horizon?

Why this comes before the grid, not after
-----------------------------------------
A backtest sees one path through a huge space of choices -- which bonds, how many, how
long, what wings -- and answers "did this particular recipe make money". Run enough
recipes and one will, whether or not there is anything to find. An information
coefficient asks the prior question on far more evidence and with far fewer knobs: over
**every** bond on **every** day, does a higher score go with a bond that subsequently
richens?

The arithmetic is the point. The baseline butterfly book has 1,407 trades. The IC
surface behind it is built from ~81,000 bond-days. If a signal has real content the IC
finds it with an order of magnitude more data and no selection rule at all; if the IC is
flat and a grid cell is not, the grid cell is a search artefact and should be read as one.

What is being predicted
-----------------------
The forward change in the bond's **richness residual** -- its yield against the local
fitted curve -- not its yield. A yield forecast is mostly a duration forecast, and every
bond in a ten-year band shares it, so an IC on raw yields measures whether the signal
knows where rates are going. Residualising leaves the idiosyncratic part, which is the
only part a butterfly is exposed to.

Sign convention: ``resid_bp > 0`` is CHEAP. A bond that richens sees its residual FALL.
So the forward return of a long position is ``-(resid[t+h] - resid[t])`` and a signal
with positive IC is one whose high scores precede richening -- the same buy-is-positive
convention the signal module uses throughout.

Reading the number
------------------
Cross-sectional Spearman IC, averaged over dates, with a t-statistic computed across
dates (not across observations -- adjacent bonds on one day are not independent draws).
A daily IC of 0.02-0.05 is a real, tradeable effect in equity-land; here the bar is set
by cost instead, and the translation is done explicitly in the notebook rather than left
as an impression: a butterfly round trip in this sector costs 0.30-0.95bp against a
cross-sectional residual dispersion of about 1.1bp, so a signal needs to explain a large
fraction of that dispersion, not a detectable one.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


def forward_residual_return(
    universe: pd.DataFrame, horizons: Sequence[int], *, resid_col: str = "resid_bp"
) -> pd.DataFrame:
    """Add ``fwd_{h}`` = -(resid[t+h] - resid[t]) in bp, per CUSIP.

    Shifted along each CUSIP's own observation sequence rather than by calendar days, so
    a bond that drops out of the gated universe for a week does not silently get a
    return measured across the hole.
    """
    d = universe.sort_values(["cusip", "date"]).copy()
    g = d.groupby("cusip")[resid_col]
    for h in horizons:
        d[f"fwd_{h}"] = -(g.shift(-h) - d[resid_col])
    return d


def newey_west_t(x: np.ndarray, lags: int) -> float:
    """t-statistic of the mean of ``x``, corrected for overlapping observations.

    This is not a refinement, it is a correction to an error. A 63-day forward return
    sampled every day shares 62 of its 63 days with the next observation, so the IC
    series is enormously autocorrelated and the naive
    ``mean / (sd / sqrt(n))`` treats ~2,400 overlapping windows as ~2,400 independent
    draws. It is not close: the naive t on the richness control at 63 days is +51, and
    the same series with a Newey-West correction at 62 lags is a fraction of that.

    The direction of the error matters for how this study reads. Every headline t here
    is inflated by the same mechanism, so the *ranking* of signals is roughly preserved
    and the *significance* of each is overstated -- which makes a small effect look
    established rather than marginal.
    """
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 10:
        return np.nan
    e = x - x.mean()
    gamma0 = float(e @ e) / n
    var = gamma0
    for L in range(1, min(int(lags), n - 1) + 1):
        cov = float(e[L:] @ e[:-L]) / n
        var += 2.0 * (1.0 - L / (lags + 1.0)) * cov      # Bartlett kernel
    if var <= 0:
        return np.nan
    return float(x.mean() / np.sqrt(var / n))


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 5:
        return np.nan
    x, y = a[ok], b[ok]
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    sx, sy = rx.std(), ry.std()
    if sx == 0 or sy == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def ic_table(
    universe: pd.DataFrame,
    signal_cols: Sequence[str],
    horizons: Sequence[int] = (1, 5, 10, 21, 42, 63),
    *,
    exec_lag: int = 1,
    min_names: int = 8,
) -> pd.DataFrame:
    """Mean cross-sectional Spearman IC per (signal, horizon), with a date-level t.

    ``exec_lag`` shifts the SIGNAL forward before it meets the return, so the IC is
    measured on the same causal footing as the backtest: a score from the file stamped T
    is matched against a return that starts at T+lag.
    """
    d = forward_residual_return(universe, horizons)
    if exec_lag:
        d = d.sort_values(["cusip", "date"])
        for c in signal_cols:
            d[c] = d.groupby("cusip")[c].shift(exec_lag)

    # Group ONCE, not once per (signal, horizon). The naive form re-runs
    # ``d.groupby("date")`` for every cell of the surface -- 13 signals x 6 horizons is
    # 78 full passes over ~81,000 rows, ~200,000 group extractions -- and it was by far
    # the slowest thing in the notebook. Slicing precomputed positional blocks turns it
    # into one pass.
    d = d.sort_values("date", kind="stable")
    dates = d["date"].to_numpy()
    bounds = np.flatnonzero(np.r_[True, dates[1:] != dates[:-1], True])
    blocks = [(a, b) for a, b in zip(bounds[:-1], bounds[1:]) if b - a >= min_names]
    cols = {c: d[c].to_numpy(float) for c in signal_cols}
    cols.update({f"fwd_{h}": d[f"fwd_{h}"].to_numpy(float) for h in horizons})

    rows = []
    for sig in signal_cols:
        sig_arr = cols[sig]
        for h in horizons:
            fwd_arr = cols[f"fwd_{h}"]
            per_date = [_spearman(sig_arr[a:b], fwd_arr[a:b]) for a, b in blocks]
            v = np.array([x for x in per_date if np.isfinite(x)], float)
            if v.size < 20:
                continue
            rows.append({
                "signal": sig, "horizon": h, "n_dates": v.size,
                "ic_mean": float(v.mean()), "ic_sd": float(v.std(ddof=1)),
                #: NAIVE t -- treats overlapping windows as independent. Kept only so the
                #: inflation is visible next to the corrected number.
                "ic_t_naive": float(v.mean() / (v.std(ddof=1) / np.sqrt(v.size))),
                #: The one to read. Newey-West at h-1 lags, which is exactly the overlap
                #: an h-day forward return sampled daily carries.
                "ic_t": newey_west_t(v, lags=max(1, h - 1)),
                "ic_hit": float((v > 0).mean()),
                # Annualised information ratio of the IC series, the scale-free way to
                # compare a signal at 1 day against the same signal at 63.
                "ic_ir": float(v.mean() / v.std(ddof=1) * np.sqrt(252 / max(1, h))),
            })
    return pd.DataFrame(rows)


def decile_spread(
    universe: pd.DataFrame,
    signal_col: str,
    horizon: int = 10,
    *,
    n_buckets: int = 5,
    exec_lag: int = 1,
) -> pd.DataFrame:
    """Mean forward residual return by signal bucket, in bp.

    The IC is a rank statistic and says nothing about magnitude; a butterfly has to beat
    a cost quoted in basis points. This is the same question in the units the decision is
    actually made in, and it also shows whether the relationship is monotone or lives
    entirely in one tail.
    """
    d = forward_residual_return(universe, [horizon])
    if exec_lag:
        d = d.sort_values(["cusip", "date"])
        d[signal_col] = d.groupby("cusip")[signal_col].shift(exec_lag)
    d = d.dropna(subset=[signal_col, f"fwd_{horizon}"])
    if d.empty:
        return pd.DataFrame()

    d["bucket"] = d.groupby("date")[signal_col].transform(
        lambda x: pd.qcut(x.rank(method="first"), n_buckets, labels=False, duplicates="drop"))
    out = d.groupby("bucket").agg(
        n=(f"fwd_{horizon}", "size"),
        mean_bp=(f"fwd_{horizon}", "mean"),
        med_bp=(f"fwd_{horizon}", "median"),
        sd_bp=(f"fwd_{horizon}", "std"),
        mean_score=(signal_col, "mean"),
    )
    out["t"] = out["mean_bp"] / (out["sd_bp"] / np.sqrt(out["n"]))
    return out


def long_short_series(
    universe: pd.DataFrame,
    signal_col: str,
    horizon: int = 10,
    *,
    n_names: int = 3,
    exec_lag: int = 1,
) -> pd.Series:
    """Per-date mean forward return of (top n_names minus bottom n_names), in bp.

    The closest costless analogue of the traded book: same selection rule, same horizon,
    no butterfly wings and no spread. The gap between this and the backtest's gross P&L
    is what the wings and the overlap rule cost in signal, and the gap between this and
    its net P&L is the spread.
    """
    d = forward_residual_return(universe, [horizon])
    if exec_lag:
        d = d.sort_values(["cusip", "date"])
        d[signal_col] = d.groupby("cusip")[signal_col].shift(exec_lag)
    d = d.dropna(subset=[signal_col, f"fwd_{horizon}"])

    out = {}
    for dt, g in d.groupby("date", sort=True):
        if len(g) < 2 * n_names:
            continue
        r = g.sort_values(signal_col)
        out[dt] = float(r[f"fwd_{horizon}"].tail(n_names).mean()
                        - r[f"fwd_{horizon}"].head(n_names).mean())
    return pd.Series(out, name=f"{signal_col}_ls_{horizon}d").sort_index()
