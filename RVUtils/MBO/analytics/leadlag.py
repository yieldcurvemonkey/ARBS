"""Lead-lag on asynchronous book data, without imposing a grid.

The existing ``RVUtils.lead_lag`` estimators (Levy area, lagged cross-correlation,
Granger) all need two series on one clock.  At book resolution that is exactly
the wrong thing to do: sampling asynchronous series onto a common grid drives
measured comovement toward zero as the interval shrinks -- the **Epps effect** --
so a study run only on a grid finds its answer pulled toward "no relationship" by
the sampling rather than by the market.  :func:`epps_curve` measures that decay on
your own data rather than taking it on trust.

The estimator that needs no grid is Hayashi-Yoshida: sum the product of every pair
of increments whose observation intervals overlap, and nothing else.  No
interpolation, no previous-tick, no synchronisation bias.

**Three things this module deliberately refuses to do**, all of them from
Hoffmann, Rosenbaum & Yoshida (Bernoulli 19(2), 2013):

1. **It reports no t-statistic or standard error for the lag.**  Their Proposition
   2 states there is *no* random variable Z such that the rescaled estimation
   error converges in distribution -- no central limit theorem exists, because
   part of the error is the deterministic distance from the true lag to the search
   grid.  A Wald-type interval here would be decoration with no asymptotic
   justification.  What is available, and what :class:`LeadLagResult` reports, is
   that almost surely the true lag lies within one maximal mesh of the estimate.
2. **It flags the degeneracy rather than hiding it.**  When the correlation is of
   the order of the square root of the mesh, maximising the contrast does not
   locate the lag at all -- the peak is indistinguishable from the noise floor.
   ``degenerate`` says so.
3. **It offers a direction statistic that does not commit to an argmax.**  The
   Huth-Abergel lead-lag ratio compares the whole positive-lag mass against the
   negative-lag mass, which is far more stable than a single peak when the
   contrast is flat.

The contrast function has a known shape -- a triangular peak of half-width equal
to the mesh, sitting on a Gaussian floor -- so a lead-lag plot that shows a broad
smooth bump rather than a hat is showing you noise, not a lag.
"""
from __future__ import annotations

import dataclasses
from typing import Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from numba import njit

__all__ = [
    "DEGENERACY_MULTIPLE",
    "LeadLagResult",
    "lead_lag_placebo",
    "epps_curve",
    "hayashi_yoshida",
    "lead_lag",
    "lead_lag_curve",
    "lead_lag_ratio",
]


#: Safety multiple on the Hoffmann-Rosenbaum-Yoshida degeneracy floor.  Their
#: result is an order-of-magnitude rate, so a finite-sample flag needs a margin;
#: this is a judgment call rather than a theorem, and :func:`lead_lag_placebo` is
#: the honest test when the answer matters.
DEGENERACY_MULTIPLE = 3.0


@njit(cache=True, nogil=True)
def _hy_cross(tx0, tx1, rx, ty0, ty1, ry, shift):
    """Sum r_i r_j over interval pairs that overlap, with Y shifted by ``shift``.

    Two-pointer sweep rather than the O(n*m) double loop: both interval sets are
    sorted, and the first Y interval that can overlap X's i-th advances
    monotonically with i.
    """
    n = rx.shape[0]
    m = ry.shape[0]
    total = 0.0
    n_pairs = 0
    j0 = 0
    for i in range(n):
        a0 = tx0[i]
        a1 = tx1[i]
        # advance past Y intervals that end at or before this X interval starts
        while j0 < m and (ty1[j0] + shift) <= a0:
            j0 += 1
        j = j0
        while j < m and (ty0[j] + shift) < a1:
            total += rx[i] * ry[j]
            n_pairs += 1
            j += 1
    return total, n_pairs


def _increments(ts: np.ndarray, px: np.ndarray
                ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Interval starts, ends and increments, dropping non-finite observations."""
    t = np.asarray(ts, dtype=np.int64)
    p = np.asarray(px, dtype=np.float64)
    ok = np.isfinite(p)
    t, p = t[ok], p[ok]
    if t.size < 2:
        return (np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0, np.float64))
    order = np.argsort(t, kind="stable")
    t, p = t[order], p[order]
    return t[:-1], t[1:], np.diff(p)


def hayashi_yoshida(ts_x, px_x, ts_y, px_y, shift_ns: int = 0) -> dict:
    """Hayashi-Yoshida cumulative covariance and correlation.

    Sums ``r_i^X r_j^Y`` over every pair of increments whose observation intervals
    overlap.  Unbiased and consistent for the integrated covariance as the mesh
    goes to zero, with no common grid and therefore no synchronisation bias.

    ``shift_ns`` shifts every Y timestamp before the overlap test.  Note the
    normaliser is **not** re-shifted: it stays the unlagged realised variance of
    each series, which is what makes the lagged quantity a correlation-scaled
    contrast comparable across lags.
    """
    ax0, ax1, rx = _increments(ts_x, px_x)
    ay0, ay1, ry = _increments(ts_y, px_y)
    if rx.size == 0 or ry.size == 0:
        return {"cov": np.nan, "corr": np.nan, "n_pairs": 0,
                "rv_x": np.nan, "rv_y": np.nan}
    cov, n_pairs = _hy_cross(ax0, ax1, rx, ay0, ay1, ry, np.int64(shift_ns))
    rv_x = float(np.sum(rx * rx))
    rv_y = float(np.sum(ry * ry))
    denom = np.sqrt(rv_x * rv_y)
    return {
        "cov": float(cov),
        "corr": float(cov / denom) if denom > 0 else np.nan,
        "n_pairs": int(n_pairs),
        "rv_x": rv_x,
        "rv_y": rv_y,
    }


def lead_lag_curve(ts_x, px_x, ts_y, px_y,
                   lags_ns: Sequence[int]) -> pd.DataFrame:
    """The shifted Hayashi-Yoshida contrast over a grid of lags.

    A positive lag means **X leads Y**: Y's timestamps are pulled back, so Y's
    later moves line up with X's earlier ones.
    """
    ax0, ax1, rx = _increments(ts_x, px_x)
    ay0, ay1, ry = _increments(ts_y, px_y)
    if rx.size == 0 or ry.size == 0:
        return pd.DataFrame(columns=["lag_ns", "corr", "cov", "n_pairs"])

    rv_x = float(np.sum(rx * rx))
    rv_y = float(np.sum(ry * ry))
    denom = np.sqrt(rv_x * rv_y)
    rows = []
    for lag in lags_ns:
        cov, n_pairs = _hy_cross(ax0, ax1, rx, ay0, ay1, ry, np.int64(-int(lag)))
        rows.append({
            "lag_ns": int(lag),
            "corr": float(cov / denom) if denom > 0 else np.nan,
            "cov": float(cov),
            "n_pairs": int(n_pairs),
        })
    return pd.DataFrame(rows)


def lead_lag_ratio(curve: pd.DataFrame) -> float:
    """Huth-Abergel lead-lag ratio: positive-lag mass over negative-lag mass.

    ``LLR = sum rho(l)^2 / sum rho(-l)^2`` over matched positive and negative
    lags; ``LLR > 1`` means X leads Y.  Preferred to reading a single argmax when
    the contrast is flat, because it uses the whole curve and does not depend on
    one peak surviving noise.
    """
    if curve.empty:
        return float("nan")
    pos = curve[curve["lag_ns"] > 0]
    neg = curve[curve["lag_ns"] < 0]
    if pos.empty or neg.empty:
        return float("nan")
    num = float(np.nansum(pos["corr"].to_numpy() ** 2))
    den = float(np.nansum(neg["corr"].to_numpy() ** 2))
    return num / den if den > 0 else float("inf")


@dataclasses.dataclass
class LeadLagResult:
    """An estimated lead-lag, with the only uncertainty statement that is defensible."""

    lag_ns: int
    corr_at_peak: float
    llr: float
    #: Maximal distance between consecutive observations across both series.  The
    #: contrast peak is a triangle of this half-width, so the estimate cannot
    #: resolve anything finer.
    mesh_ns: int
    #: Almost surely the true lag lies in this interval.  There is no central
    #: limit theorem for this estimator, so there is no standard error to quote
    #: and this interval is the strongest available statement, not a 95% band.
    interval_ns: Tuple[int, int]
    #: True when the peak correlation is of the order of the square root of the
    #: mesh over the horizon, where maximising the contrast provably fails to
    #: locate the lag.  A "significant" reading here is noise.
    degenerate: bool
    curve: pd.DataFrame

    @property
    def lag_seconds(self) -> float:
        return self.lag_ns / 1e9

    def __repr__(self) -> str:
        d = " DEGENERATE" if self.degenerate else ""
        return (f"<LeadLag {self.lag_seconds:+.4f}s +/- {self.mesh_ns / 1e9:.4f}s "
                f"rho={self.corr_at_peak:+.4f} LLR={self.llr:.2f}{d}>")


def lead_lag(ts_x, px_x, ts_y, px_y,
             max_lag_ns: int = 5_000_000_000,
             n_lags: int = 81) -> LeadLagResult:
    """Estimate by which lag X leads Y, on a symmetric grid around zero.

    The estimate is the lag maximising the absolute shifted Hayashi-Yoshida
    contrast, with ties broken toward the smaller lag.

    **No standard error is returned, and that is deliberate.**  Hoffmann,
    Rosenbaum and Yoshida prove no central limit theorem exists for this
    estimator: part of the error is the deterministic gap between the true lag and
    the search grid, which no rescaling controls.  What holds almost surely is
    that the true lag lies within one maximal mesh of the estimate, and that is
    what ``interval_ns`` reports.
    """
    lags = np.unique(np.linspace(-int(max_lag_ns), int(max_lag_ns), int(n_lags))
                     .round().astype(np.int64))
    curve = lead_lag_curve(ts_x, px_x, ts_y, px_y, lags)
    if curve.empty or curve["corr"].isna().all():
        return LeadLagResult(0, float("nan"), float("nan"), 0, (0, 0), True, curve)

    absr = curve["corr"].abs().to_numpy()
    best = int(np.nanargmax(absr))
    # ties toward the smaller absolute lag: a flat contrast should not be read as
    # a large lead just because the grid happens to end there.
    tied = np.flatnonzero(np.isclose(absr, absr[best], rtol=0, atol=1e-15))
    best = int(tied[np.argmin(np.abs(curve["lag_ns"].to_numpy()[tied]))])

    ax0, ax1, _ = _increments(ts_x, px_x)
    ay0, ay1, _ = _increments(ts_y, px_y)
    mesh = 0
    if ax1.size:
        mesh = max(mesh, int(np.max(ax1 - ax0)))
    if ay1.size:
        mesh = max(mesh, int(np.max(ay1 - ay0)))

    span = 1
    if ax1.size and ay1.size:
        span = max(1, int(max(ax1[-1], ay1[-1]) - min(ax0[0], ay0[0])))
    rho = float(curve["corr"].to_numpy()[best])
    # HRY degeneracy: once |rho| falls to the ORDER of sqrt(mesh / horizon), the
    # peak is indistinguishable from the noise floor and maximising the contrast
    # provably fails to locate the lag.  Their statement is a rate, not a
    # threshold, so a finite-sample flag needs a safety multiple; 3 is a judgment
    # call and is stated as one rather than dressed up.  For a real answer on
    # whether a peak is meaningful, use lead_lag_placebo, which is the inference
    # the theory actually endorses -- no central limit theorem exists here.
    floor = DEGENERACY_MULTIPLE * float(np.sqrt(mesh / span)) if span > 0 else 1.0
    degenerate = not np.isfinite(rho) or abs(rho) <= floor

    lag = int(curve["lag_ns"].to_numpy()[best])
    return LeadLagResult(
        lag_ns=lag,
        corr_at_peak=rho,
        llr=lead_lag_ratio(curve),
        mesh_ns=mesh,
        interval_ns=(lag - mesh, lag + mesh),
        degenerate=bool(degenerate),
        curve=curve,
    )


def epps_curve(ts_x, px_x, ts_y, px_y,
               freqs: Sequence[str] = ("100ms", "1s", "5s", "30s", "60s", "300s"),
               ) -> pd.DataFrame:
    """Grid-sampled correlation against sampling interval, beside the HY estimate.

    This is the diagnostic that says whether a grid-based result can be trusted at
    the frequency it was computed at.  If the correlation collapses as the
    interval shrinks while the Hayashi-Yoshida figure stays put, the collapse is
    the Epps effect -- an artefact of synchronising asynchronous observations --
    and not a property of the market.
    """
    sx = pd.Series(np.asarray(px_x, dtype=float),
                   index=pd.to_datetime(np.asarray(ts_x, dtype="int64"), utc=True))
    sy = pd.Series(np.asarray(px_y, dtype=float),
                   index=pd.to_datetime(np.asarray(ts_y, dtype="int64"), utc=True))
    hy = hayashi_yoshida(ts_x, px_x, ts_y, px_y)

    rows = []
    for f in freqs:
        gx = sx.resample(f).last().ffill()
        gy = sy.resample(f).last().ffill()
        idx = gx.index.union(gy.index)
        dx = gx.reindex(idx).ffill().diff()
        dy = gy.reindex(idx).ffill().diff()
        both = pd.concat([dx, dy], axis=1).dropna()
        n = len(both)
        c = float(both.iloc[:, 0].corr(both.iloc[:, 1])) if n > 2 else np.nan
        rows.append({"freq": f, "n": n, "grid_corr": c,
                     "hy_corr": hy["corr"]})
    out = pd.DataFrame(rows)
    out["epps_gap"] = out["hy_corr"] - out["grid_corr"]
    return out


def lead_lag_placebo(ts_x, px_x, ts_y, px_y,
                     max_lag_ns: int = 5_000_000_000,
                     n_lags: int = 81,
                     n_placebo: int = 200,
                     seed: int = 0) -> dict:
    """Is the observed contrast peak bigger than chance?  A permutation test.

    This is the inference the theory endorses.  Hoffmann, Rosenbaum and Yoshida
    prove no central limit theorem exists for the lead-lag estimator, so there is
    no standard error and no t-statistic to compute; what remains is to ask how
    often a peak this large arises when the relationship is destroyed but every
    other feature of the data -- the observation times, the mesh, the marginal
    return distributions, the number of increments -- is preserved.

    The Y increments are permuted rather than the Y prices, so the surrogate keeps
    the same realised variance and the same irregular clock and differs only in
    which move happened when.  Permuting prices instead would change the return
    distribution and make the null too easy to reject.

    Returns the observed peak, the placebo distribution's quantiles, and the
    empirical p-value: the share of placebos whose peak absolute correlation
    reached the observed one.
    """
    obs = lead_lag(ts_x, px_x, ts_y, px_y, max_lag_ns=max_lag_ns, n_lags=n_lags)
    ay0, ay1, ry = _increments(ts_y, px_y)
    if ry.size == 0 or not np.isfinite(obs.corr_at_peak):
        return {"lag_ns": obs.lag_ns, "corr_at_peak": obs.corr_at_peak,
                "p_value": np.nan, "n_placebo": 0,
                "placebo_p95": np.nan, "placebo_median": np.nan}

    ts_y_arr = np.asarray(ts_y, dtype=np.int64)
    rng = np.random.default_rng(seed)
    peaks = np.empty(int(n_placebo), dtype=np.float64)
    for k in range(int(n_placebo)):
        shuffled = np.concatenate([[0.0], rng.permutation(ry)]).cumsum()
        # rebuild a price path with the same increments in a different order
        t_sur = np.concatenate([[ay0[0]], ay1])
        c = lead_lag_curve(ts_x, px_x, t_sur, shuffled,
                           np.unique(np.linspace(-int(max_lag_ns), int(max_lag_ns),
                                                 int(n_lags)).round().astype(np.int64)))
        peaks[k] = float(np.nanmax(np.abs(c["corr"].to_numpy()))) if len(c) else np.nan

    good = peaks[np.isfinite(peaks)]
    p = float(np.mean(good >= abs(obs.corr_at_peak))) if good.size else np.nan
    return {
        "lag_ns": obs.lag_ns,
        "corr_at_peak": obs.corr_at_peak,
        "p_value": p,
        "n_placebo": int(good.size),
        "placebo_median": float(np.median(good)) if good.size else np.nan,
        "placebo_p95": float(np.quantile(good, 0.95)) if good.size else np.nan,
        "degenerate": obs.degenerate,
    }
