"""ING "Deconstructing the EUR yield curve" descriptive screen.

Replicates the METHOD of ING Global Markets Research, "Rates Strategy:
Deconstructing the EUR yield curve" (2020-01-15) on a daily par-rate grid:

1.  Bootstrap an annual zero/discount curve per day from par OIS rates at
    1Y..30Y using the ANNUAL-FIXED-LEG approximation: a par swap rate ``s_N``
    with annual payments implies ``s_N * sum_{i=1..N} DF_i + DF_N = 1``, solved
    recursively as ``DF_N = (1 - s_N * sum_{i<N} DF_i) / (1 + s_N)``.
2.  Non-overlapping 1y forwards ``F_k = DF_k / DF_{k+1} - 1`` ("kF1Y").
3.  Walk-forward rolling-window PCA on forward LEVELS, PC1 only; the signal is
    the residual of each forward vs its PC1 fit, in bp.
4.  Percentile bands of each forward's residual vs its own trailing history.
5.  3m roll-down of a receiver per forward point from the same day's curve.
6.  The daily value-vs-carry frontier: cross-sectional regression of residual
    (bp) on 3m roll-down (bp/3m).

APPROXIMATIONS (this is a screen, not a pricer):

*   Annual fixed leg with unit year fractions (no calendars, no day counts,
    no payment lags); EUR OIS actually pays annual ACT/360.  The par input is
    read as the quoted grid without convention adjustment.
*   Missing integer par tenors (e.g. 21Y..24Y, 26Y..29Y) are linearly
    interpolated in PAR space from the printed integer tenors before
    bootstrapping.  Days with fewer than ``min_printed`` printed integer
    tenors in 1Y..30Y, or missing 30Y, are skipped.  A missing 1Y is
    replaced by the linear par-space anchor ``s_1 = 2*s_2 - s_3`` and
    flagged (see :func:`integer_par_grid`) - the anchor makes the recursion
    feasible but the implied 1F1Y on such days is construction, not data.
*   The 3m-aged forward is read off the forward strip by LINEAR interpolation
    in the forward-start dimension: f(k - 0.25) = 0.75*f(k) + 0.25*f(k-1),
    so roll = 0.25 * (f(k) - f(k-1)).  The k=1 point uses the spot-1y node
    (0F1Y) as its left neighbour.
*   PCA loadings are refit MONTHLY from up to ``window`` (default 756)
    business days strictly BEFORE the month start (no same-month lookahead)
    and held fixed within the month; the window mean is frozen with the
    loadings.  Months whose trailing window has fewer than ``min_window``
    days produce NaN residuals (ramp-in).
*   Percentile ranks/bands use the trailing ``window`` residuals through t-1
    (the current day is excluded from its own band); fewer than ``min_obs``
    observations produce NaN ranks.

All rate inputs/outputs are in PERCENT unless a name says ``_bp``.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "INTEGER_TENORS",
    "integer_par_grid",
    "bootstrap_discounts",
    "annual_forwards",
    "forward_labels",
    "rolldown_3m",
    "rolling_pc1_residuals",
    "residual_percentiles",
    "daily_frontier",
    "reversion_gate",
]

INTEGER_TENORS = np.arange(1, 31)

_INT_TENOR_RE = re.compile(r"^(\d+)Y$")


# ---------------------------------------------------------------------------
# 1. Par grid -> dense integer-tenor par grid
# ---------------------------------------------------------------------------

def integer_par_grid(
    par_grid: pd.DataFrame,
    min_printed: int = 15,
    anchor_1y: str = "extrapolate_missing",
) -> Tuple[pd.DataFrame, pd.Index, pd.Series]:
    """Extract 1Y..30Y integer-tenor par rates, filling gaps linearly in par space.

    The 1Y ANCHOR: the bootstrap recursion needs a 1Y par rate, but spliced
    pre-RFR vendor history may print nothing below 2Y.  When 1Y did not
    print, ``s_1 = 2*s_2 - s_3`` (linear par-space extrapolation from the two
    shortest printed points) is used and the day is FLAGGED.  The anchor
    exists only to make the recursion feasible - forwards at k >= 2 are
    insensitive to it (error ~ (s_3 - s_2) * ds_1, sub-bp); the implied 1F1Y
    on flagged days is construction, not data, and must not be surfaced as a
    market 1y1y.

    Parameters
    ----------
    par_grid : DataFrame
        Daily par rates in PERCENT, columns are tenor tokens ('1Y', '15M',
        '30Y', ...).  Only integer-year columns in 1..30 are used.
    min_printed : int
        Minimum number of PRINTED (non-NaN) integer tenors in 1Y..30Y for a
        day to be kept.  Days missing 30Y are always dropped (no long-end
        extrapolation).
    anchor_1y : str
        'extrapolate_missing' (default): use the printed 1Y when available,
        else the linear anchor; 'printed_only': drop days without a printed
        1Y; 'always_extrapolate': use the linear anchor on every day, even
        when 1Y printed (uniform construction, for splice-seam-free
        diagnostics).

    Returns
    -------
    (dense, skipped, front_extrapolated) : (DataFrame, Index, Series)
        ``dense`` has integer columns 1..30 (par, percent) with no NaNs and
        only the surviving days; ``skipped`` are the dropped dates;
        ``front_extrapolated`` is a bool Series over ``dense.index`` - True
        where the 1Y anchor is constructed rather than printed.
    """
    if anchor_1y not in ("extrapolate_missing", "printed_only", "always_extrapolate"):
        raise ValueError(f"unknown anchor_1y policy {anchor_1y!r}")
    cols: Dict[int, str] = {}
    for c in par_grid.columns:
        m = _INT_TENOR_RE.match(str(c))
        if m:
            n = int(m.group(1))
            if 1 <= n <= 30:
                cols[n] = c
    for need in (1, 2, 3, 30):
        if need not in cols:
            raise ValueError(f"par grid must contain a {need}Y column")

    tenors = np.array(sorted(cols))
    raw = par_grid[[cols[n] for n in tenors]].to_numpy(dtype=float)

    printed = ~np.isnan(raw)
    n_printed = printed.sum(axis=1)
    j1 = int(np.flatnonzero(tenors == 1)[0])
    j2 = int(np.flatnonzero(tenors == 2)[0])
    j3 = int(np.flatnonzero(tenors == 3)[0])
    j30 = int(np.flatnonzero(tenors == 30)[0])
    has_1y = printed[:, j1]
    can_extrap = printed[:, j2] & printed[:, j3]

    if anchor_1y == "printed_only":
        anchor_ok = has_1y
        use_extrap = np.zeros_like(has_1y)
    elif anchor_1y == "extrapolate_missing":
        anchor_ok = has_1y | can_extrap
        use_extrap = ~has_1y & can_extrap
    else:  # always_extrapolate
        anchor_ok = can_extrap
        use_extrap = can_extrap

    keep = (n_printed >= min_printed) & printed[:, j30] & anchor_ok

    dense = np.empty((int(keep.sum()), INTEGER_TENORS.size))
    kept_rows = np.flatnonzero(keep)
    for out_i, i in enumerate(kept_rows):
        vals = raw[i].copy()
        mask = printed[i].copy()
        if use_extrap[i]:
            vals[j1] = 2.0 * vals[j2] - vals[j3]
            mask[j1] = True
        dense[out_i] = np.interp(INTEGER_TENORS, tenors[mask], vals[mask])

    dense_df = pd.DataFrame(
        dense, index=par_grid.index[keep], columns=INTEGER_TENORS.tolist()
    )
    skipped = par_grid.index[~keep]
    front_extrapolated = pd.Series(
        use_extrap[keep], index=dense_df.index, name="front_extrapolated"
    )
    return dense_df, skipped, front_extrapolated


# ---------------------------------------------------------------------------
# 2. Bootstrap + forwards
# ---------------------------------------------------------------------------

def bootstrap_discounts(
    par_pct: pd.DataFrame,
    zero_bounds: Tuple[float, float] = (-0.10, 0.30),
) -> pd.DataFrame:
    """Bootstrap annual discount factors from integer-tenor par rates.

    ``par_pct`` must be the dense output of :func:`integer_par_grid`
    (columns 1..30, PERCENT, no NaN).  Recursion:
    ``DF_N = (1 - s_N * sum_{i<N} DF_i) / (1 + s_N)`` with ``s_N`` in decimal.

    Sanity gate: every implied annual zero rate ``DF_N ** (-1/N) - 1`` must
    lie inside ``zero_bounds`` (decimal).  This is deliberately loose enough
    for the negative-EUR era (DF > 1 is legal, DFs need not be monotone) but
    fails LOUDLY (ValueError) if percent input is fed as decimal or vice
    versa.
    """
    cols = list(par_pct.columns)
    if cols != INTEGER_TENORS.tolist():
        raise ValueError("bootstrap_discounts expects integer columns 1..30")
    s = par_pct.to_numpy(dtype=float) / 100.0
    n_days = s.shape[0]
    dfs = np.empty_like(s)
    cum = np.zeros(n_days)
    for j, _tenor in enumerate(INTEGER_TENORS):
        s_n = s[:, j]
        df_n = (1.0 - s_n * cum) / (1.0 + s_n)
        dfs[:, j] = df_n
        cum = cum + df_n

    if np.any(dfs <= 0.0) or np.any(~np.isfinite(dfs)):
        bad = int(np.sum((dfs <= 0.0) | ~np.isfinite(dfs)))
        raise ValueError(
            f"bootstrap produced {bad} non-positive/non-finite discount factors "
            "- par input is probably not in percent"
        )
    zeros = dfs ** (-1.0 / INTEGER_TENORS[None, :]) - 1.0
    lo, hi = zero_bounds
    out = (zeros < lo) | (zeros > hi)
    if np.any(out):
        worst = float(zeros[out][np.argmax(np.abs(zeros[out]))])
        raise ValueError(
            f"{int(out.sum())} implied annual zero rates outside ({lo:+.2f}, "
            f"{hi:+.2f}) decimal (worst {worst:+.4f}) - par input is probably "
            "not in percent"
        )
    return pd.DataFrame(dfs, index=par_pct.index, columns=cols)


def annual_forwards(dfs: pd.DataFrame, include_spot: bool = False) -> pd.DataFrame:
    """Non-overlapping 1y forwards ``F_k = DF_k / DF_{k+1} - 1`` in PERCENT.

    Columns are the forward-start year k = 1..29 ("kF1Y").  With
    ``include_spot=True`` the k=0 column (spot 1y, ``DF_0 = 1``) is included
    - needed internally for the roll-down strip, excluded from screen output.
    """
    d = dfs.to_numpy(dtype=float)
    with_spot = np.column_stack([np.ones(d.shape[0]), d])  # DF_0..DF_30
    fwd = (with_spot[:, :-1] / with_spot[:, 1:] - 1.0) * 100.0  # k = 0..29
    ks = list(range(0, 30)) if include_spot else list(range(1, 30))
    start = 0 if include_spot else 1
    return pd.DataFrame(fwd[:, start:30], index=dfs.index, columns=ks)


def forward_labels(ks: Iterable[int]) -> list:
    """Map forward-start years to 'kF1Y' labels."""
    return [f"{int(k)}F1Y" for k in ks]


# ---------------------------------------------------------------------------
# 3. Carry / roll
# ---------------------------------------------------------------------------

def rolldown_3m(forwards_with_spot: pd.DataFrame) -> pd.DataFrame:
    """3m roll-down of a receiver per forward point, in BP per 3m.

    ``forwards_with_spot`` must include the k=0 column
    (``annual_forwards(dfs, include_spot=True)``).  On an unchanged curve the
    kF1Y receiver ages into the (k-0.25)F1Y point; with linear interpolation
    on the strip, ``roll_k = f(k) - f(k-0.25) = 0.25 * (f(k) - f(k-1))``.
    Positive roll-down = the rate rolls DOWN the curve = receiver-friendly
    carry on an upward-sloping strip.
    """
    if 0 not in forwards_with_spot.columns:
        raise ValueError("rolldown_3m needs the k=0 (spot 1y) column")
    f = forwards_with_spot.to_numpy(dtype=float)
    roll = 0.25 * (f[:, 1:] - f[:, :-1]) * 100.0  # percent -> bp
    ks = list(forwards_with_spot.columns[1:])
    return pd.DataFrame(roll, index=forwards_with_spot.index, columns=ks)


# ---------------------------------------------------------------------------
# 4. Walk-forward rolling PC1 residuals
# ---------------------------------------------------------------------------

def rolling_pc1_residuals(
    forwards_pct: pd.DataFrame,
    window: int = 756,
    min_window: int = 504,
    return_loadings: bool = False,
):
    """Walk-forward PC1 residuals of forward LEVELS, in bp.

    For each calendar month, loadings (and the window mean) are fit by PCA
    (covariance of levels, largest eigenvector) on up to ``window`` rows
    strictly BEFORE the month start, then held fixed for every day of that
    month.  Residual = level - (mean + score * loading), score = loading .
    (level - mean).  Months with fewer than ``min_window`` trailing rows get
    NaN residuals.

    Returns residuals in bp (same shape as input); with
    ``return_loadings=True`` also a dict {month_start_date: (mean, loading,
    explained_share)}.
    """
    x = forwards_pct.to_numpy(dtype=float)
    idx = forwards_pct.index
    n, m = x.shape
    resid = np.full((n, m), np.nan)
    loadings: Dict[pd.Timestamp, tuple] = {}

    months = idx.to_period("M")
    # positions where a new month starts
    starts = np.flatnonzero(np.r_[True, months[1:] != months[:-1]])
    for si, start in enumerate(starts):
        end = starts[si + 1] if si + 1 < len(starts) else n
        lo = max(0, start - window)
        win = x[lo:start]
        if win.shape[0] < min_window:
            continue
        mean = win.mean(axis=0)
        cov = np.cov(win - mean, rowvar=False)
        evals, evecs = np.linalg.eigh(cov)
        v = evecs[:, -1]
        if v.sum() < 0:
            v = -v
        share = float(evals[-1] / evals.sum())
        if return_loadings:
            loadings[idx[start]] = (mean.copy(), v.copy(), share)
        block = x[start:end] - mean
        scores = block @ v
        resid[start:end] = (block - scores[:, None] * v[None, :]) * 100.0  # bp

    resid_df = pd.DataFrame(resid, index=idx, columns=forwards_pct.columns)
    if return_loadings:
        return resid_df, loadings
    return resid_df


# ---------------------------------------------------------------------------
# 5. Percentile bands
# ---------------------------------------------------------------------------

def residual_percentiles(
    residuals_bp: pd.DataFrame,
    window: int = 756,
    min_obs: int = 252,
    bands: Tuple[float, float, float] = (5.0, 50.0, 95.0),
) -> Dict[str, pd.DataFrame]:
    """Trailing percentile rank + bands per forward, current day EXCLUDED.

    For each date t and tenor, the band/rank uses the residuals in
    ``(t - window, t - 1]`` (at most ``window`` observations, NaNs dropped);
    fewer than ``min_obs`` valid observations -> NaN.  Rank is the fraction
    of history strictly below the current residual, in [0, 1].

    Returns dict with keys 'rank', 'p5', 'p50', 'p95' (DataFrames aligned to
    the input).
    """
    idx = residuals_bp.index
    cols = residuals_bp.columns
    n = len(idx)
    out = {k: np.full((n, len(cols)), np.nan) for k in ("rank", "p5", "p50", "p95")}

    from numpy.lib.stride_tricks import sliding_window_view

    for j, c in enumerate(cols):
        x = residuals_bp[c].to_numpy(dtype=float)
        if n <= 1:
            continue
        # vectorized: full windows first
        if n > window:
            sw = sliding_window_view(x, window)[:-1]  # sw[i] -> history for t=i+window
            cur = x[window:]
            valid = ~np.isnan(sw)
            nval = valid.sum(axis=1)
            ok = (nval >= min_obs) & ~np.isnan(cur)
            if ok.any():
                below = np.nansum(sw < cur[:, None], axis=1)
                rank = np.where(ok, below / np.maximum(nval, 1), np.nan)
                out["rank"][window:, j] = rank
                rows = np.flatnonzero(ok) + window
                hist = sw[ok]
                if np.isnan(hist).any():
                    p = np.nanpercentile(hist, bands, axis=1)
                else:
                    p = np.percentile(hist, bands, axis=1)
                out["p5"][rows, j] = p[0]
                out["p50"][rows, j] = p[1]
                out["p95"][rows, j] = p[2]
        # ramp-in region: partial windows (full windows handled above)
        t_hi = min(window - 1, n - 1)
        for t in range(1, t_hi + 1):
            hist = x[0:t]
            hist = hist[~np.isnan(hist)]
            if hist.size < min_obs or np.isnan(x[t]):
                continue
            out["rank"][t, j] = float(np.mean(hist < x[t]))
            p = np.percentile(hist, bands)
            out["p5"][t, j] = p[0]
            out["p50"][t, j] = p[1]
            out["p95"][t, j] = p[2]

    return {
        k: pd.DataFrame(v, index=idx, columns=cols) for k, v in out.items()
    }


# ---------------------------------------------------------------------------
# 6. Value-vs-carry frontier
# ---------------------------------------------------------------------------

def daily_frontier(
    residuals_bp: pd.DataFrame,
    rolldown_bp: pd.DataFrame,
    ks: Iterable[int] = tuple(range(2, 16)),
) -> pd.DataFrame:
    """Per-day cross-sectional OLS of residual (bp) on 3m roll-down (bp/3m).

    Restricted to forward-start years ``ks`` (default 2F1Y..15F1Y, per ING).
    Returns DataFrame with columns slope / intercept / r2 / n.
    """
    ks = [k for k in ks]
    y = residuals_bp[ks].to_numpy(dtype=float)
    x = rolldown_bp[ks].to_numpy(dtype=float)
    valid = ~(np.isnan(y) | np.isnan(x))
    n_valid = valid.sum(axis=1)

    xm = np.where(valid, x, 0.0)
    ym = np.where(valid, y, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        nx = np.maximum(n_valid, 1)
        mx = xm.sum(axis=1) / nx
        my = ym.sum(axis=1) / nx
        dx = np.where(valid, x - mx[:, None], 0.0)
        dy = np.where(valid, y - my[:, None], 0.0)
        sxx = (dx * dx).sum(axis=1)
        sxy = (dx * dy).sum(axis=1)
        syy = (dy * dy).sum(axis=1)
        slope = sxy / sxx
        intercept = my - slope * mx
        r2 = (sxy * sxy) / (sxx * syy)

    bad = (n_valid < max(3, len(ks) // 2)) | (sxx <= 0) | (syy <= 0)
    slope[bad] = np.nan
    intercept[bad] = np.nan
    r2[bad] = np.nan
    return pd.DataFrame(
        {"slope": slope, "intercept": intercept, "r2": r2, "n": n_valid},
        index=residuals_bp.index,
    )


# ---------------------------------------------------------------------------
# 7. Mean-reversion gate (descriptive oracle)
# ---------------------------------------------------------------------------

def reversion_gate(
    residuals_bp: pd.DataFrame,
    rank: pd.DataFrame,
    p50: pd.DataFrame,
    horizons: Tuple[int, ...] = (21, 63, 126),
    low: float = 0.05,
    high: float = 0.95,
    cost_bp: float = 1.0,
    revert_frac: float = 0.5,
    revert_horizon: int = 63,
) -> pd.DataFrame:
    """Descriptive reversion statistics for band-breach events.

    An EVENT is any day whose trailing rank is <= ``low`` or >= ``high``
    (events on consecutive days overlap - they are NOT independent trades).
    Dislocation ``d = r_t - p50_t`` (vs the trailing median AT the fire
    date); reversion at horizon h is ``sign(d) * (r_t - r_{t+h})`` - positive
    means the residual moved toward that median (can exceed |d| on
    overshoot).  Events within the last ``max(horizons)`` rows are excluded
    at EVERY horizon, so n_fired is the same event set across horizons.

    Returns one row per forward tenor: n_fired, median |d|, median reversion
    per horizon, fraction of events with reversion > ``revert_frac`` * |d|
    by ``revert_horizon``, and the cost benchmark.
    """
    rows = []
    max_h = max(horizons)
    for c in residuals_bp.columns:
        r = residuals_bp[c].to_numpy(dtype=float)
        rk = rank[c].to_numpy(dtype=float)
        med = p50[c].to_numpy(dtype=float)
        n = r.size
        fired = (~np.isnan(rk)) & ((rk <= low) | (rk >= high)) & ~np.isnan(med)
        # need the longest horizon observable
        fired[n - max_h:] = False
        t_idx = np.flatnonzero(fired)
        row = {"tenor": f"{c}F1Y", "n_fired": int(t_idx.size)}
        if t_idx.size == 0:
            for h in horizons:
                row[f"med_reversion_{h}bd"] = np.nan
            row["med_abs_dislocation_bp"] = np.nan
            row[f"frac_revert_gt{int(revert_frac*100)}pct_{revert_horizon}bd"] = np.nan
            row["cost_bp"] = cost_bp
            rows.append(row)
            continue
        d = r[t_idx] - med[t_idx]
        sgn = np.sign(d)
        row["med_abs_dislocation_bp"] = float(np.median(np.abs(d)))
        for h in horizons:
            rev = sgn * (r[t_idx] - r[t_idx + h])
            row[f"med_reversion_{h}bd"] = float(np.nanmedian(rev))
            if h == revert_horizon:
                frac = rev / np.abs(d)
                row[
                    f"frac_revert_gt{int(revert_frac*100)}pct_{revert_horizon}bd"
                ] = float(np.nanmean(frac > revert_frac))
        row["cost_bp"] = cost_bp
        rows.append(row)
    return pd.DataFrame(rows).set_index("tenor")
