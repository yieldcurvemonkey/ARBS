r"""Shared loading, day-type flags and the level/slope/idiosyncratic decomposition.

One module so that the hygiene decisions -- which dates are excluded, what counts
as an FOMC day, how the cross-section is split into level, slope and idiosyncratic
-- are made once and cannot drift between the reversal script, the holdings
regression and the month-end event study.

The decomposition, and why it is the number that matters
--------------------------------------------------------
A butterfly is level-neutral by construction and, at these maturities, very nearly
slope-neutral too. So the part of the 15:00->16:00 move that a fly can harvest is
neither the size of the move nor its cross-sectional standard deviation: it is what
survives after each date's cross-section has had its level and its curve shape
projected out. :func:`decompose` regresses each date's seam move on ``[1, x, x^2]``
in centred time-to-maturity and calls the residual idiosyncratic.

``x`` is time to maturity, not modified duration. Duration was never warmed
intraday for this universe (``CITI_DURATION`` is not in the cached layer), and over
a 13-31 year band the two are monotone in each other; the quadratic term absorbs
the curvature that separates them. Stated as a limitation rather than hidden: a
coupon-driven part of the seam move would land in the idiosyncratic bucket here,
which if anything makes the idiosyncratic number an OVERSTATEMENT of what a
level-neutral structure can see.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA = ROOT / "notebooks" / "backtests" / "etf_rebalance" / "_data"

#: The measured FedInvest bid/offer round trip for a butterfly (RESULTS.md).
FLY_ROUND_TRIP_BP = 0.535

#: A cross-section smaller than this cannot support a quadratic fit with a residual
#: that means anything. Same floor as ``curve.fit_residuals``.
MIN_BONDS = 12


def load_panel(*, drop_early_close: bool = True) -> pd.DataFrame:
    p = pd.read_parquet(DATA / "seam_panel.parquet")
    if drop_early_close:
        p = p[~p["is_early_close"]]
    return p.reset_index(drop=True)


# ------------------------------------------------------------------ day types

def fomc_decision_dates() -> pd.DatetimeIndex:
    """FOMC decision dates, derived from the repo's own central-bank registry.

    ``SDRUtils.analytics.fomc.load_fomc_schedule`` returns each meeting's
    ``effective_date``, and in this registry that IS the decision date, not the day
    after it: the entries read ``mar22 -> 2022-03-16``, ``may23 -> 2023-05-03``,
    which are the statement days themselves. This was checked against the registry
    rather than assumed -- an earlier version of this function shifted back one
    business day on the usual "SOFR applies the next day" convention, and the
    self-check in ``etf_seam_reversal.py`` caught it: the flagged dates showed
    LESS 14:00-15:00 activity than ordinary ones, which is what you get when you
    label the quiet pre-FOMC session as the meeting.
    """
    from SDRUtils.analytics.fomc import load_fomc_schedule

    eff = pd.to_datetime(load_fomc_schedule("USD-SOFR-1D")["effective_date"])
    return pd.DatetimeIndex(sorted(set(eff)))


def long_auction_dates() -> pd.DatetimeIndex:
    """Original-issue 20y and 30y auction dates from the fiscaldata reference table.

    LIMITATION, stated rather than papered over: the fiscaldata reference table
    carries ONE auction date per CUSIP, the original issue. The two monthly
    reopenings of each 20y and 30y are not in it, so roughly two thirds of long-bond
    auction days fall into the "ordinary" bucket here. That mislabelling is
    conservative for the question being asked -- it contaminates the CONTROL with
    auction days, which shrinks any auction-day effect toward zero rather than
    manufacturing one.
    """
    from RVUtils.ETFRebalance.bond_panel import reference_frame

    ref = reference_frame()
    ref["auction_date"] = pd.to_datetime(ref["auction_date"], errors="coerce")
    long_end = ref["oi"].astype(str).isin(["20-Year", "30-Year"])
    d = ref.loc[long_end, "auction_date"].dropna()
    return pd.DatetimeIndex(sorted(set(d)))


def day_types(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per date with the four mutually-exclusive-by-priority day flags."""
    dates = pd.DatetimeIndex(sorted(set(pd.DatetimeIndex(dates))))
    me = pd.Series(dates).dt.to_period("M").dt.to_timestamp("M")
    cal_to_me = (me.to_numpy() - dates.to_numpy()).astype("timedelta64[D]").astype(int)

    # "Month end" = the last three CALENDAR days of the month, the bucket the daily
    # study and the backfill census both used, so the numbers are comparable.
    is_me = pd.Series(cal_to_me <= 2, index=dates)
    is_fomc = pd.Series(dates.isin(fomc_decision_dates()), index=dates)
    is_auc = pd.Series(dates.isin(long_auction_dates()), index=dates)

    out = pd.DataFrame({"cal_days_to_month_end": cal_to_me.astype(int),
                        "is_month_end": is_me, "is_fomc": is_fomc,
                        "is_auction": is_auc}, index=dates)
    out.index.name = "date"
    # A priority ordering so every date lands in exactly one reported bucket.
    kind = np.where(out["is_fomc"], "fomc",
                    np.where(out["is_month_end"], "month_end",
                             np.where(out["is_auction"], "auction", "ordinary")))
    out["day_type"] = kind
    return out


# --------------------------------------------------------------- decomposition

def _fit_one(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, np.ndarray]:
    """OLS of ``y`` on ``[1, x, x^2]``; returns (b0, b1, b2, residual)."""
    A = np.column_stack([np.ones_like(x), x, x ** 2])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return float(beta[0]), float(beta[1]), float(beta[2]), y - A @ beta


def decompose(panel: pd.DataFrame, *, col: str, min_bonds: int = MIN_BONDS
              ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split ``col`` into level, slope, curvature and idiosyncratic, per date.

    Returns ``(per_date, per_obs)``. ``per_obs`` carries ``idio`` -- the part of the
    move a level- and slope-neutral structure can actually reach.
    """
    rows, obs = [], []
    for d, g in panel.groupby("date", sort=True):
        g = g.dropna(subset=[col, "ttm"])
        if len(g) < min_bonds:
            continue
        y = g[col].to_numpy(float)
        raw = g["ttm"].to_numpy(float)
        x = (raw - raw.mean()) / max(1e-9, raw.std())
        b0, b1, b2, resid = _fit_one(x, y)
        # The "total" here is the UNCENTRED second moment. Using the variance would
        # make the level share identically zero by construction -- a bug that
        # printed 0.0 in the first run of this decomposition and would have been
        # read as "there is no level move" next to a 1.27 bp level standard
        # deviation. Mean-square is the quantity a level move actually inflates.
        tot = float(np.mean(y ** 2))
        after_level = float(np.mean((y - y.mean()) ** 2))
        A1 = np.column_stack([np.ones_like(x), x])
        b, *_ = np.linalg.lstsq(A1, y, rcond=None)
        after_slope = float(np.mean((y - A1 @ b) ** 2))
        rows.append({
            "date": d, "n": len(g),
            "level_bp": float(y.mean()), "slope_bp_per_sd": b1, "curv_bp": b2,
            "sd_total_bp": float(np.std(y)),
            "sd_after_level_bp": float(np.sqrt(after_level)),
            "sd_after_slope_bp": float(np.sqrt(after_slope)),
            "sd_idio_bp": float(np.std(resid)),
            "mad_idio_bp": float(1.4826 * np.median(np.abs(resid - np.median(resid)))),
            "var_total": tot, "var_after_level": after_level,
            "var_after_slope": after_slope, "var_idio": float(np.mean(resid ** 2)),
        })
        o = g[["date", "isin", "cusip", "ttm"]].copy()
        o["raw"] = y
        o["idio"] = resid
        obs.append(o)
    per_date = pd.DataFrame(rows)
    per_obs = pd.concat(obs, ignore_index=True) if obs else pd.DataFrame()
    return per_date, per_obs


def newey_west_t(x: pd.Series, lags: int | None = None) -> tuple[float, float, float, int]:
    """(mean, se, t, n) for the mean of a series, Newey-West corrected."""
    v = pd.Series(x).dropna().to_numpy(float)
    n = len(v)
    if n < 8:
        return (float("nan"),) * 3 + (n,)
    if lags is None:
        lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    e = v - v.mean()
    g0 = float(np.dot(e, e) / n)
    s = g0
    for L in range(1, max(1, lags) + 1):
        if L >= n:
            break
        gl = float(np.dot(e[L:], e[:-L]) / n)
        s += 2.0 * (1.0 - L / (lags + 1.0)) * gl
    se = float(np.sqrt(max(s, 0.0) / n))
    m = float(v.mean())
    return m, se, (m / se if se > 0 else float("nan")), n
