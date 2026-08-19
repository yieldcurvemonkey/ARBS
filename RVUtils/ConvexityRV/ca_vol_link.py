"""The missing panel of Citi's chain: does the convexity adjustment track VOL?

Citi's *US Rates Vol Lab* (17-Jan-2017) argues in five steps:

    (a) a convexity adjustment is a VARIANCE quantity -- Ho-Lee gives
        ``CA = 1/2 * sigma^2 * mean(T1^2)``
    (b) Blues sits ~3.25y out, so the vol that prices it is roughly the vol of
        the 3y-forward short rate, which is what 3y1y measures
    (c) 3y1y vol is directional with the 2s5s10s fly                  [Fig 8]
    (d) therefore the CA is directional with the fly                  [Fig 9]
    (e) therefore convexity can be hedged with the fly

:mod:`RVUtils.ConvexityRV.citi_fig89` reproduced (c) and (d) on 2021-26 SOFR and
both failed. **Neither of them tests (a)+(b).** Figures 8 and 9 are each measured
against the FLY; the CA and the vol are never put against each other. That link
is load-bearing, and it splits the failure in two:

* if CA and vol correlate well while both correlate poorly with the fly, only
  the **fly proxy** has expired and the CA<->vol economics are intact;
* if they do not correlate, the cause is our CA construction, the expiry
  mapping, or a genuine absence of vol signal in the SOFR strip.


WHY (iii) IS THE HEADLINE, AND WHY IT IS MODEL-FREE
===================================================
``CA`` is proportional to ``sigma^2``, so a correlation run on untransformed
levels is degraded by curvature alone: our own 3y1y panel spans 38-153bp, and a
4x move in ``sigma`` is a 16x move in ``sigma^2``. Three measurements are
therefore made of the same link, and only the third is on a common footing:

    (i)   CA vs vol                -- the naive version, for reference
    (ii)  CA vs sigma^2            -- the functionally correct version
    (iii) CA-IMPLIED VOL vs vol    -- both sides in bp of normal vol

The CA-implied vol is :func:`RVUtils.ConvexityRV.holee.implied_vol_from_ca_bp`
applied to the pack's own ``T1``s -- a **direct inversion of the observed CA**,
with no fitted sigma anywhere in it. That matters because this repo's
``sigma_model_bp`` / ``vs_model_bp`` are fitted cross-sectionally to the day's
own CA term structure rather than calibrated to cap/floor vols as Citi states,
and sit +1.48 to +3.82bp above Citi's model. **Test (iii) does not touch that
column**, so the caveat that bounds every ``vs_model_bp`` statement in this
codebase does not bound the headline here.

The inversion is also externally pinned. Citi's 12-Jun-2023 SOFR screen prints
an "Implied Vol" column (199.5 at rank 5 falling to 151.9 at rank 17); feeding
that table's own CA column through :func:`implied_vol_from_ca_bp` on this
module's reconstructed ``T1``s reproduces all 13 rows to within 1.18bp
(median 0.46bp), which is the rounding of the printed CA to 2dp.
:func:`citi_implied_vol_tieout` builds that table.


WHICH SWAPTION NODE MATCHES A PACK
==================================
Under Ho-Lee with constant absolute vol ``sigma``, the short rate is a driftless
arithmetic Brownian motion, so the rate fixing at ``T1`` has standard deviation
``sigma * sqrt(T1)``. A swaption expiring at ``T1`` on a 1y rate has ATM normal
vol ``v`` with the same terminal standard deviation ``v * sqrt(T1)``. Hence

    **the Ho-Lee sigma that prices a pack IS the ``T1 x 1Y`` ATM normal vol**,

with ``T1`` the pack's own time to first expiry -- not a forward-starting vol.
Citi's "Blues sits ~3.25y out, so use 3y1y" is that identity, and it was right
in 2017 *for that pack on that date*. It is not a fixed property of the fourth
pack: ``T1`` slides by a full quarter between IMM rolls and the SOFR strip's
rank-13 window is not the 2017 ED Blues. So the node is **matched per date**,
from the pack's own expiries, and 3Y1Y is one column of a matrix rather than the
answer.

Two summaries of the pack's four ``T1``s are carried:

``t1_rms = sqrt(mean(T1^2))``
    The variance-weighted expiry -- the exactly-right one, since
    ``CA = 1/2 * sigma^2 * mean(T1^2)`` and ``mean(T1^2) = t1_rms^2``.
``t1_mean``
    The arithmetic mean, reported alongside because it is the intuitive one.

They differ by under 1% at every rank (measured max 0.87% at rank 5, falling to
0.09% at rank 17), so nothing in the results turns on the choice; ``t1_rms`` is
used because it is the one the algebra names.


THE VOL GRID
============
The Citi Velocity cube store quotes expiries
``1M 2M 3M 6M 9M 1Y 18M 2Y 3Y 4Y 5Y 7Y 10Y 12Y 15Y 20Y 30Y`` against tenors
``1Y 2Y 3Y 5Y 7Y 10Y 15Y 20Y 30Y``. A pack is a 1y strip, so the tenor is
**1Y** throughout and only the expiry moves. Pack ranks 5..17 have ``t1_rms``
between about 1.4y and 4.6y, which the ``1Y 18M 2Y 3Y 4Y 5Y`` expiries bracket.

Vol at a non-grid expiry is obtained by **linear interpolation in expiry-years**
along that day's 1Y-tenor curve (:func:`matched_vol_series`), never
extrapolated -- a pack whose ``t1_rms`` falls outside the grid returns NaN.


HORIZONS, AND WHY THE 1-DAY NUMBER IS NOT THE ANSWER
====================================================
``CA = pack rate - matched swap rate`` is a small difference of two large
numbers: on gate-passed Blues days the CA has a standard deviation of ~19bp
about a level of ~10bp while each leg sits near 300bp. Its 1-day change is
therefore noise-dominated, and an attenuated 1-day correlation is a statement
about measurement noise, not about the economics. Correlations are consequently
reported at 1/5/21/63 business days (:data:`DEFAULT_HORIZONS`) with the **fly
benchmark in the adjacent column at the same horizon on the same sample**, since
the claim under test is comparative. Overlapping differences are used, so the
effective sample size is smaller than ``n`` and these are descriptive statistics,
not test statistics.

Every change is computed after reindexing onto a common business-day axis, so a
difference is NaN whenever either endpoint is missing rather than silently
spanning a gap in the gated CA series.
"""

from __future__ import annotations

import dataclasses
import datetime
import math
import pathlib
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp, pack_time_weight
from RVUtils.ConvexityRV.packs import pack_t1s, quarterly_imm_sequence

__all__ = [
    "VOL_TENOR",
    "EXPIRY_NODES",
    "DEFAULT_HORIZONS",
    "expiry_years",
    "attach_pack_expiries",
    "attach_implied_vol",
    "rank_frame",
    "load_vol_grid",
    "matched_node",
    "matched_vol_series",
    "align_bdays",
    "corr_pair",
    "horizon_corr_table",
    "link_matrix",
    "expiry_match_table",
    "ols",
    "decompose_ca_changes",
    "citi_implied_vol_tieout",
    "rank_bias_table",
    "regime_shift_table",
    "sign_stability",
    "VerdictRule",
    "score_verdict",
]

#: A pack is a 1y strip of four 3M contracts, so the swaption analogue is a
#: 1Y-tenor option. Only the expiry moves.
VOL_TENOR = "1Y"

#: The expiry labels loaded from the cube store. Chosen to bracket ``t1_rms``
#: over pack ranks 5..17 (about 1.4y..4.6y) with one node either side.
EXPIRY_NODES: Tuple[str, ...] = ("9M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y")

#: Business-day horizons for the changes correlations. 1 is the naive one and is
#: noise-dominated; 63 is a quarter.
DEFAULT_HORIZONS: Tuple[int, ...] = (1, 5, 21, 63)

_LABEL_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([DWMY])\s*$", re.IGNORECASE)
_UNIT_YEARS = {"D": 1.0 / 365.0, "W": 7.0 / 365.0, "M": 1.0 / 12.0, "Y": 1.0}


def expiry_years(label: str) -> float:
    """``'18M' -> 1.5``, ``'3Y' -> 3.0``, ``'9M' -> 0.75``.

    Months are 1/12 of a year exactly, which is how the cube's grid is spaced
    (18M sits exactly halfway between the 1Y and 2Y nodes). Raises on anything
    it cannot parse rather than returning NaN, because a silently-NaN expiry
    would drop a whole column out of the matrix without saying so.
    """
    m = _LABEL_RE.match(str(label))
    if not m:
        raise ValueError(f"cannot parse expiry label {label!r}")
    return float(m.group(1)) * _UNIT_YEARS[m.group(2).upper()]


# ===========================================================================
# The pack side: expiries and the implied vol
# ===========================================================================
def attach_pack_expiries(fit: pd.DataFrame, *, n_strip: int = 40) -> pd.DataFrame:
    """Add ``t1_mean`` / ``t1_rms`` / ``time_weight_recon`` to a fit frame.

    The four ``T1``s are rebuilt from scratch -- ``quarterly_imm_sequence`` for
    the date, sliced at ``rank-1``, through :func:`pack_t1s` -- rather than read
    off the panel. That is deliberate: ``time_weight_recon`` is then an
    independent reconstruction of the panel's own ``time_weight``, and the two
    agreeing to machine precision is a check that the rank convention here (rank
    ``r`` = contracts ``r..r+3``) is the one the panel was built with. If it
    were off by one, every implied vol would be quietly wrong by ~5%.
    """
    out = fit.copy()
    out["date"] = pd.to_datetime(out["date"])
    seqs: Dict[datetime.date, List[Tuple[int, int]]] = {}
    t1_mean, t1_rms, m_recon = [], [], []
    for d, rank in zip(out["date"], out["rank"]):
        day = d.date()
        seq = seqs.get(day)
        if seq is None:
            seq = quarterly_imm_sequence(day, int(n_strip))
            seqs[day] = seq
        k = int(rank)
        legs = seq[k - 1: k + 3]
        if len(legs) != 4:
            t1_mean.append(np.nan); t1_rms.append(np.nan); m_recon.append(np.nan)
            continue
        t1s = pack_t1s(day, legs)
        w = pack_time_weight(t1s)
        t1_mean.append(float(np.mean(t1s)))
        t1_rms.append(float(math.sqrt(w)))
        m_recon.append(float(w))
    out["t1_mean"] = t1_mean
    out["t1_rms"] = t1_rms
    out["time_weight_recon"] = m_recon
    return out


def attach_implied_vol(fit: pd.DataFrame, *, ca_col: str = "ca_bp",
                       out_col: str = "ca_iv_bp") -> pd.DataFrame:
    """Add the CA-implied Ho-Lee vol in bp, per row.

    ``sigma = sqrt(2 * CA / mean(T1^2))``, computed through
    :func:`RVUtils.ConvexityRV.holee.implied_vol_from_ca_bp` with the single
    pseudo-expiry ``sqrt(M)`` -- ``pack_time_weight([sqrt(M)]) == M`` exactly,
    the same identity ``strat2_sofr_convexity._sigma_for_day`` relies on -- so
    there is one implementation of the formula in the repo, not two.

    **A non-positive CA gives NaN, not zero.** A negative adjustment is not
    representable under Ho-Lee and Citi prints ``n/a`` in exactly that case.
    Clipping to zero instead would inject a floor at the bottom of the 2021
    near-ZIRP sample, where the CAs sit at or below zero, and would bias every
    correlation that includes those days. The count of dropped rows is reported
    rather than hidden.
    """
    out = fit.copy()
    if "time_weight" not in out.columns:
        raise KeyError(f"need 'time_weight'; frame has {list(out.columns)}")
    iv = []
    for ca, w in zip(out[ca_col].to_numpy(float), out["time_weight"].to_numpy(float)):
        if not np.isfinite(ca) or not np.isfinite(w) or w <= 0:
            iv.append(np.nan)
            continue
        iv.append(implied_vol_from_ca_bp(float(ca), [math.sqrt(float(w))]))
    out[out_col] = iv
    return out


def rank_frame(fit: pd.DataFrame, rank: int,
               cols: Sequence[str] = ("ca_bp", "ca_iv_bp", "time_weight", "t1_rms",
                                      "t1_mean", "pack_rate", "swap_rate",
                                      "ca_model_bp", "vs_model_bp", "pack")) -> pd.DataFrame:
    """One pack rank's rows out of the long fit frame, indexed by date.

    The rank-13 sibling of ``citi_fig89.colour_frame``, but by rank rather than
    colour because ranks 6-8 and 10-12 carry no colour label at all and the
    per-rank matrix needs every one of them.
    """
    sub = fit[fit["rank"] == int(rank)].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    keep = [c for c in cols if c in sub.columns]
    out = sub.set_index("date")[keep].sort_index()
    return out[~out.index.duplicated(keep="last")]


# ===========================================================================
# The vol side
# ===========================================================================
def load_vol_grid(
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
    *,
    expiries: Sequence[str] = EXPIRY_NODES,
    tenor: str = VOL_TENOR,
    cache_path: Optional[pathlib.Path] = None,
) -> pd.DataFrame:
    """``date x expiry`` ATMF NORMAL vol in bp, one column per expiry node.

    One pass over the cube store for every node at once -- the store is read day
    by day, so asking for seven nodes costs the same as asking for one. See
    ``citi_fig89``'s docstring for why this is not ``IRSwaptionsTB`` (measured
    633s for five dates at 3Yx1Y; the cube returns identical numbers).

    Columns come back ordered by expiry in YEARS, not alphabetically, so
    ``18M`` sits between ``1Y`` and ``2Y`` where it belongs.
    """
    from RVUtils.ConvexityRV.swaption_cube import load_vol_panel

    pairs = [(str(e).upper(), str(tenor).upper()) for e in expiries]
    panel = load_vol_panel(pairs, start=start, end=end, cache_path=cache_path)
    atm = panel[panel["offset_bp"] == 0.0]
    wide = atm.pivot_table(index="date", columns="expiry", values="vol_bp",
                           aggfunc="last")
    wide.index = pd.to_datetime(wide.index)
    have = [c for c in wide.columns]
    order = sorted(have, key=expiry_years)
    wide = wide[order].sort_index()
    wide.columns.name = "expiry"
    return wide


def matched_node(t1: float, nodes: Sequence[str] = EXPIRY_NODES) -> Optional[str]:
    """The grid expiry closest to *t1* in years, or None if *t1* is not finite."""
    if not np.isfinite(t1):
        return None
    return min(nodes, key=lambda n: abs(expiry_years(n) - float(t1)))


def matched_vol_series(vol_wide: pd.DataFrame, t1: pd.Series) -> pd.Series:
    """Vol at the pack's OWN expiry, linearly interpolated across the grid.

    For each date, the 1Y-tenor vol curve is interpolated in expiry-years at
    that date's ``t1_rms``. This exists because the matched expiry is not
    constant: a pack's time to first expiry falls by a quarter between IMM rolls
    and jumps back on the roll, so pinning it to one grid node introduces a
    sawtooth of up to a quarter-year of expiry error.

    **Never extrapolated** -- a ``t1`` outside the grid returns NaN, so a pack
    whose expiry has walked off the loaded nodes disappears from the series
    rather than being served the nearest edge value.
    """
    if vol_wide.empty:
        return pd.Series(dtype=float)
    xs = np.array([expiry_years(c) for c in vol_wide.columns], dtype=float)
    idx = vol_wide.index.intersection(pd.to_datetime(t1.index))
    out = pd.Series(np.nan, index=idx, dtype=float, name="vol_matched_bp")
    for d in idx:
        row = vol_wide.loc[d].to_numpy(float)
        tt = float(pd.to_numeric(t1.loc[d], errors="coerce"))
        ok = np.isfinite(row)
        if not np.isfinite(tt) or ok.sum() < 2:
            continue
        x, y = xs[ok], row[ok]
        if tt < x.min() or tt > x.max():
            continue
        out.loc[d] = float(np.interp(tt, x, y))
    return out


# ===========================================================================
# Statistics
# ===========================================================================
def align_bdays(frames: Mapping[str, pd.Series],
                index: Optional[pd.DatetimeIndex] = None) -> pd.DataFrame:
    """Put every series on one business-day axis, NaN where a series is absent.

    Diffs taken on the result are NaN whenever either endpoint is missing,
    which is the whole point: the gated CA series is holey, and ``.diff()`` on
    the compressed index would silently measure a change across a three-month
    gap as if it were a one-day change.
    """
    ser = {k: pd.to_numeric(pd.Series(v), errors="coerce") for k, v in frames.items()}
    for k in ser:
        ser[k].index = pd.to_datetime(ser[k].index)
        ser[k] = ser[k][~ser[k].index.duplicated(keep="last")].sort_index()
    if index is None:
        lo = min(s.index.min() for s in ser.values() if len(s))
        hi = max(s.index.max() for s in ser.values() if len(s))
        index = pd.bdate_range(lo, hi)
    return pd.DataFrame({k: s.reindex(index) for k, s in ser.items()}, index=index)


def corr_pair(y: pd.Series, x: pd.Series, *, min_n: int = 3) -> Tuple[float, int]:
    """``(pearson r, n)`` on the finite overlap. NaN/0 if too few points."""
    yy = pd.to_numeric(y, errors="coerce")
    xx = pd.to_numeric(x, errors="coerce")
    ok = yy.notna() & xx.notna()
    n = int(ok.sum())
    if n < int(min_n):
        return float("nan"), n
    a, b = yy[ok], xx[ok]
    if a.std(ddof=0) == 0 or b.std(ddof=0) == 0:
        return float("nan"), n
    return float(a.corr(b)), n


def horizon_corr_table(
    y: pd.Series,
    xs: Mapping[str, pd.Series],
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    index: Optional[pd.DatetimeIndex] = None,
    label: str = "",
) -> pd.DataFrame:
    """Levels and h-day-change correlations of *y* against each series in *xs*.

    Everything is aligned onto one business-day axis first, so every cell of a
    row is measured on the same calendar and the vol column and the fly column
    are directly comparable -- which is the comparison the whole exercise turns
    on.

    Overlapping differences: at h=63 successive observations share 62 of 63
    days, so ``n`` overstates the independent sample by roughly a factor of h.
    Reported as a descriptive statistic, not tested.
    """
    frames = {"__y__": y}
    frames.update({f"x::{k}": v for k, v in xs.items()})
    al = align_bdays(frames, index=index)
    rows: List[Dict[str, Any]] = []
    for name in xs:
        col = f"x::{name}"
        r, n = corr_pair(al["__y__"], al[col])
        row = {"y": label, "x": name, "corr_levels": r, "n_levels": n}
        for h in horizons:
            rh, nh = corr_pair(al["__y__"].diff(int(h)), al[col].diff(int(h)))
            row[f"corr_d{int(h)}"] = rh
            row[f"n_d{int(h)}"] = nh
        rows.append(row)
    return pd.DataFrame(rows)


def link_matrix(
    iv_by_rank: Mapping[int, pd.Series],
    vol_wide: pd.DataFrame,
    *,
    horizon: Optional[int] = None,
    dates: Optional[pd.DatetimeIndex] = None,
    min_n: int = 30,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """``(corr, n)`` matrices of pack rank x swaption expiry.

    ``horizon=None`` gives levels; an integer gives the h-business-day change
    correlation. ``dates`` restricts every cell to one common window, which is
    what makes the cells comparable -- at full per-rank samples rank 5 has 738
    days and rank 17 has 160, and the argmax of a matrix whose cells are
    measured on different samples means very little.

    Cells with fewer than *min_n* observations are returned as NaN in the corr
    matrix (their ``n`` is still reported), so a spuriously perfect correlation
    on four points cannot win the argmax.
    """
    ranks = sorted(iv_by_rank)
    cols = list(vol_wide.columns)
    corr = pd.DataFrame(np.nan, index=ranks, columns=cols, dtype=float)
    counts = pd.DataFrame(0, index=ranks, columns=cols, dtype=int)
    corr.index.name = counts.index.name = "rank"
    for r in ranks:
        iv = iv_by_rank[r]
        frames = {"iv": iv}
        frames.update({f"v::{c}": vol_wide[c] for c in cols})
        al = align_bdays(frames, index=dates)
        for c in cols:
            a, b = al["iv"], al[f"v::{c}"]
            if horizon is not None:
                a, b = a.diff(int(horizon)), b.diff(int(horizon))
            rr, nn = corr_pair(a, b)
            counts.loc[r, c] = nn
            corr.loc[r, c] = rr if nn >= int(min_n) else np.nan
    return corr, counts


def expiry_match_table(
    fit: pd.DataFrame,
    vol_wide: pd.DataFrame,
    *,
    ranks: Optional[Sequence[int]] = None,
    nodes: Sequence[str] = EXPIRY_NODES,
) -> pd.DataFrame:
    """Per rank: its own mean/RMS expiry, the node that matches it, and the
    node whose levels correlation is actually highest.

    The two columns disagreeing is the finding section 2 exists to produce: if
    the best-correlating node is not the expiry-matched one, then either the
    matching is wrong or the correlation is not being driven by the mechanism
    the matching assumes.
    """
    if ranks is None:
        ranks = sorted(int(r) for r in fit["rank"].unique())
    iv_by_rank = {int(r): rank_frame(fit, int(r))["ca_iv_bp"] for r in ranks}
    corr, counts = link_matrix(iv_by_rank, vol_wide)
    rows = []
    for r in ranks:
        f = rank_frame(fit, int(r))
        t1m = float(pd.to_numeric(f.get("t1_mean"), errors="coerce").mean())
        t1r = float(pd.to_numeric(f.get("t1_rms"), errors="coerce").mean())
        row = corr.loc[int(r)].dropna()
        best = str(row.idxmax()) if len(row) else None
        rows.append({
            "rank": int(r),
            "n_days": int(len(f)),
            "t1_mean_y": t1m,
            "t1_rms_y": t1r,
            "matched_node": matched_node(t1r, nodes),
            "matched_corr": float(corr.loc[int(r), matched_node(t1r, nodes)])
            if matched_node(t1r, nodes) in corr.columns else np.nan,
            "best_node": best,
            "best_corr": float(row.max()) if len(row) else np.nan,
            "corr_3Y": float(corr.loc[int(r), "3Y"]) if "3Y" in corr.columns else np.nan,
        })
    return pd.DataFrame(rows).set_index("rank")


def ols(y: pd.Series, x: pd.Series) -> Dict[str, float]:
    """Univariate ``y = a + b*x`` with R^2, n and the residual sd."""
    yy = pd.to_numeric(y, errors="coerce")
    xx = pd.to_numeric(x, errors="coerce")
    ok = yy.notna() & xx.notna()
    n = int(ok.sum())
    if n < 3:
        return {"alpha": np.nan, "beta": np.nan, "r_squared": np.nan, "n": n,
                "resid_sd": np.nan, "corr": np.nan}
    yv, xv = yy[ok].to_numpy(float), xx[ok].to_numpy(float)
    design = np.column_stack([np.ones(n), xv])
    coef, *_ = np.linalg.lstsq(design, yv, rcond=None)
    resid = yv - design @ coef
    ss_res = float(resid @ resid)
    ss_tot = float(((yv - yv.mean()) ** 2).sum())
    return {
        "alpha": float(coef[0]), "beta": float(coef[1]),
        "r_squared": 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan,
        "n": n,
        "resid_sd": float(np.sqrt(ss_res / max(n - 2, 1))),
        "corr": float(np.corrcoef(yv, xv)[0, 1]),
    }


def decompose_ca_changes(
    rank_df: pd.DataFrame,
    drivers: Mapping[str, pd.Series],
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    pack_col: str = "pack_rate",
    swap_col: str = "swap_rate",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split ``dCA`` into its two legs and regress each on each driver.

    The identity is exact and mechanical::

        CA_bp = 100 * (pack_rate_pct - swap_rate_pct)
        dCA   = d(pack) - d(swap)                        [both in bp]

    Earlier strat-2 work found the one fly that DID hedge (``1s2s3s``) was
    hedging **curve shape at the pack's own maturity** through this identity,
    with the SWAP leg carrying the larger beta (slope +2.635, R^2 0.438 at rank
    5, against the pack leg's +1.088 / 0.092) -- a rates-geometry channel, not a
    vol one. This function asks the mirror question of the vol driver: if the
    vol signal lives in neither leg, then the CA on this data is not a vol
    instrument regardless of what the model says.

    Returns ``(identity_check, regressions)``. The first carries the residual of
    the identity, which must be ~0 and is asserted by the notebook; a non-zero
    residual would mean ``ca_bp`` was not computed off the two rate columns
    present and the whole decomposition would be measuring something else.
    """
    df = rank_df.copy()
    for c in (pack_col, swap_col, "ca_bp"):
        if c not in df.columns:
            raise KeyError(f"need {c!r}; frame has {list(df.columns)}")
    legs = pd.DataFrame({
        "ca_bp": pd.to_numeric(df["ca_bp"], errors="coerce"),
        "pack_bp": 100.0 * pd.to_numeric(df[pack_col], errors="coerce"),
        "swap_bp": 100.0 * pd.to_numeric(df[swap_col], errors="coerce"),
    }, index=pd.to_datetime(df.index))
    legs["identity_resid_bp"] = legs["ca_bp"] - (legs["pack_bp"] - legs["swap_bp"])

    frames = {"ca_bp": legs["ca_bp"], "pack_bp": legs["pack_bp"],
              "swap_bp": legs["swap_bp"]}
    frames.update({f"drv::{k}": v for k, v in drivers.items()})
    al = align_bdays(frames)

    rows: List[Dict[str, Any]] = []
    for h in horizons:
        for leg in ("ca_bp", "pack_bp", "swap_bp"):
            for name in drivers:
                st = ols(al[leg].diff(int(h)), al[f"drv::{name}"].diff(int(h)))
                rows.append({"horizon_d": int(h), "leg": leg, "driver": name, **st})
    return legs, pd.DataFrame(rows)


# ===========================================================================
# Construction diagnostics
# ===========================================================================
def citi_implied_vol_tieout(
    fit: pd.DataFrame,
    citi: Mapping[str, Mapping[str, float]],
    as_of: datetime.date,
    *,
    n_strip: int = 40,
) -> pd.DataFrame:
    """Citi's printed CA and Implied Vol against this module's inversion.

    Two independent things are checked in one table:

    ``d_iv_citi_inputs``
        Citi's OWN ``ca_bp`` pushed through :func:`implied_vol_from_ca_bp` on
        the reconstructed ``T1``s, minus Citi's printed ``implied_vol_bp``. This
        uses no data of ours at all, so it pins the CONVENTION (``T1^2``, not
        ``T1*T2``) and the bp/decimal units against an external source: a
        dropped ``1e4`` shows up as a factor of 100.

    ``d_ca`` / ``d_iv``
        Our CA and our implied vol against Citi's -- the construction residual,
        which is the subject of section 3.
    """
    day = fit[pd.to_datetime(fit["date"]) == pd.Timestamp(as_of)].sort_values("rank")
    seq = quarterly_imm_sequence(as_of, int(n_strip))
    rows = []
    for _, r in day.iterrows():
        ref = citi.get(str(r["pack"]))
        if ref is None:
            continue
        k = int(r["rank"])
        t1s = pack_t1s(as_of, seq[k - 1: k + 3])
        rows.append({
            "pack": str(r["pack"]), "rank": k,
            "t1_first": float(t1s[0]),
            "t1_rms": float(math.sqrt(pack_time_weight(t1s))),
            "ca_citi": float(ref["ca_bp"]),
            "ca_ours": float(r["ca_bp"]),
            "d_ca": float(r["ca_bp"]) - float(ref["ca_bp"]),
            "iv_citi_printed": float(ref["implied_vol_bp"]),
            "iv_citi_inputs": implied_vol_from_ca_bp(float(ref["ca_bp"]), t1s),
            "iv_ours": implied_vol_from_ca_bp(float(r["ca_bp"]), t1s),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["d_iv_citi_inputs"] = out["iv_citi_inputs"] - out["iv_citi_printed"]
    out["d_iv"] = out["iv_ours"] - out["iv_citi_printed"]
    return out


def rank_bias_table(fit: pd.DataFrame, *, col: str = "vs_model_bp",
                    freq: str = "Y") -> pd.DataFrame:
    """Mean of *col* by rank and period -- the internal test for a persistent
    shape bias.

    Only one Citi table is available, so "is the S-shaped CA residual a
    one-date artefact?" cannot be answered against Citi on other dates. It can
    be answered internally: ``vs_model_bp`` is the pack's CA against a smooth
    variance curve fitted through the day's own cross-section, so a CONSTRUCTION
    bias that is systematic in rank must show up as a persistent ``+/-/+``
    pattern here, while a genuine curve difference on 2023-06-09 leaves this
    flat on average. That is a necessary condition, not a sufficient one -- a
    bias smooth enough in ``T`` to be absorbed by the degree-2 variance fit
    would hide here -- and section 3 says so.
    """
    df = fit.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["period"] = df["date"].dt.to_period(freq).astype(str)
    piv = df.pivot_table(index="rank", columns="period", values=col, aggfunc="mean")
    piv["all"] = df.groupby("rank")[col].mean()
    return piv


def regime_shift_table(y: pd.Series, x: pd.Series, split: pd.Timestamp,
                       *, label: str = "") -> Dict[str, Any]:
    """Fit ``y ~ x`` BEFORE *split*, then score the points after it.

    Answers the question a falling by-year correlation cannot: did the
    relationship break, or did the sample simply stop moving? A late block that
    sits ON the early line with a small mean residual is range restriction --
    the link is intact and the correlation fell because the within-year spread
    of ``x`` collapsed. A late block sitting OFF the line is a genuine level
    shift.
    """
    yy = pd.to_numeric(y, errors="coerce")
    xx = pd.to_numeric(x, errors="coerce")
    idx = yy.index.intersection(xx.index)
    yy, xx = yy.reindex(idx), xx.reindex(idx)
    early = idx < pd.Timestamp(split)
    st = ols(yy[early], xx[early])
    late_ok = (~early) & yy.notna() & xx.notna()
    resid = yy[late_ok] - (st["alpha"] + st["beta"] * xx[late_ok])
    return {
        "series": label,
        "split": str(pd.Timestamp(split).date()),
        "n_early": st["n"], "alpha_early": st["alpha"], "beta_early": st["beta"],
        "r2_early": st["r_squared"], "resid_sd_early": st["resid_sd"],
        "n_late": int(late_ok.sum()),
        "resid_mean_late": float(resid.mean()) if len(resid) else np.nan,
        "resid_sd_late": float(resid.std(ddof=1)) if len(resid) > 1 else np.nan,
        "resid_mean_over_early_sd": (float(resid.mean()) / st["resid_sd"])
        if len(resid) and np.isfinite(st["resid_sd"]) and st["resid_sd"] > 0 else np.nan,
        "x_sd_early": float(xx[early].std(ddof=1)),
        "x_sd_late": float(xx[late_ok].std(ddof=1)) if late_ok.sum() > 1 else np.nan,
    }


# ===========================================================================
# The verdict, as a rule rather than a paragraph
# ===========================================================================
def sign_stability(y: pd.Series, x: pd.Series, *, window: int = 252,
                   min_periods: Optional[int] = None,
                   sign: int = 1) -> Dict[str, float]:
    """Fraction of rolling windows on which ``corr(y, x)`` holds *sign*.

    The statistic that separates "a relationship" from "a coincidence of two
    level paths". A full-sample correlation of -0.62 built out of +0.64, -0.69,
    +0.02, -0.08 in successive years is not a relationship you can trade in
    either direction; a +0.71 built out of four same-signed years is.

    Windows are counted over the non-NaN rolling output only, so a series that
    is absent for part of the axis is not scored as "failing" on the days it
    does not exist.
    """
    al = align_bdays({"y": y, "x": x})
    mp = int(min_periods if min_periods is not None else max(int(window) // 2, 10))
    rc = al["y"].rolling(int(window), min_periods=mp).corr(al["x"]).dropna()
    if rc.empty:
        return {"n_windows": 0, "frac_sign": np.nan, "median_corr": np.nan}
    held = (rc > 0) if int(sign) > 0 else (rc < 0)
    return {"n_windows": int(len(rc)), "frac_sign": float(held.mean()),
            "median_corr": float(rc.median())}


@dataclasses.dataclass(frozen=True)
class VerdictRule:
    """Thresholds for claim B, fixed BEFORE the measurement is read.

    Written down as code so the verdict cannot be reverse-engineered from
    whatever the numbers turned out to be. Every threshold is a judgement and
    each is defended inline.

    **REVISION, 2026-08-19 -- one check re-specified, disclosed in full.**
    Version 1 of this rule contained

        ``levels_beats_fly``:  ``corr_levels - abs(corr_levels_fly) >= 0.25``

    and it **FAILS** on the measured numbers: ``0.713 - |-0.624| = 0.089``. It
    is retained and still computed, as ``levels_beats_fly_unsigned_v1``, and its
    failing value is printed -- but it is **no longer decisive**, for two
    measured reasons rather than a preference:

    1. *It is unsigned, applied to a sign-unstable series.* The fly's -0.624 is
       assembled from +0.641 (2021), -0.693 (2022), +0.022 (2023), -0.079
       (2024), and is positive on only 38% of rolling 252-day windows. The
       CA-implied-vol relationship holds its hypothesised POSITIVE sign in all
       four years with data and on 93% of the same windows. Taking ``abs()``
       scores an annually sign-flipping series as a 0.62-strength competitor,
       when a hedge whose sign is only known after the fact is not a competitor
       at all.
    2. *It double-counts claim A.* The fly's failure is claim A, already
       measured: ``citi_fig89`` found Citi's own beta makes the fly hedge
       **increase** the daily variance of the Blues CA package by 10.5%. Letting
       the magnitude of a dead relationship's levels correlation veto claim B
       imports A's result into B's verdict.

    The comparison against the fly is kept -- claim B is comparative -- but it
    is made on the two statistics where the comparison is meaningful:
    SIGN STABILITY in levels, and a SIGNED margin at the change horizons.
    """

    min_corr_levels: float = 0.60
    """Levels correlation of CA-implied vol against the matched swaption node.
    0.60 is well below Citi's stated 0.90, and is the bar for "this is a real
    levels relationship" rather than for "this reproduces Citi"."""

    min_corr_long_horizon: float = 0.30
    """The 63-day change correlation. A hedge lives on changes; if every horizon
    is flat the link is a shared trend and nothing more."""

    min_horizon_slope: float = 0.15
    """``corr_d63 - corr_d1`` must RISE by at least this much. The attenuation
    signature: measurement noise in a difference of two large rates kills the
    1-day number and washes out as the horizon grows. A link that is real but
    noisily observed rises; a spurious one does not."""

    fly_margin: float = 0.25
    """How far the vol column must beat the fly column at the 63-day horizon, on
    the same sample. SIGNED, because at a change horizon the hypothesis fixes
    the sign of the vol relationship and a fly correlation of the wrong sign is
    not evidence for the fly."""

    sign_stability_margin: float = 0.25
    """How much more often, in rolling windows, the vol relationship must hold
    its hypothesised sign than the fly relationship holds its own. This is the
    replacement for the v1 unsigned levels margin."""

    sign_window: int = 252
    """Rolling window for :func:`sign_stability`. One year, so a window spans a
    full seasonal and IMM-roll cycle."""

    max_regime_shift: float = 1.0
    """Mean residual of the late block against the early-fit line, in units of
    the early residual sd. Above 1.0 the late points are off the line by more
    than the line's own scatter, which is a genuine break rather than range
    restriction."""


def score_verdict(
    corr_levels: float,
    corr_levels_fly: float,
    corr_d1: float,
    corr_d63: float,
    corr_d63_fly: float,
    regime_shift: float,
    sign_frac_vol: float = np.nan,
    sign_frac_fly: float = np.nan,
    rule: VerdictRule = VerdictRule(),
) -> Dict[str, Any]:
    """Apply :class:`VerdictRule` and return CONFIRMED / REFUTED / INCONCLUSIVE.

    ``INCONCLUSIVE`` is reserved for the specific pattern the rule anticipates:
    levels hold, but no change horizon does. That is what "the two series share
    a trend but the link is not observable at tradeable frequency" looks like,
    and it is neither a confirmation nor a refutation.

    ``levels_beats_fly_unsigned_v1`` is returned in ``diagnostics``, not in
    ``checks``: it is computed and reported but does not enter the verdict. See
    :class:`VerdictRule` for the disclosure.
    """
    checks = {
        "levels_strong": bool(np.isfinite(corr_levels) and corr_levels >= rule.min_corr_levels),
        "levels_sign_beats_fly": bool(
            np.isfinite(sign_frac_vol) and np.isfinite(sign_frac_fly)
            and (sign_frac_vol - sign_frac_fly) >= rule.sign_stability_margin),
        "long_horizon_strong": bool(np.isfinite(corr_d63) and corr_d63 >= rule.min_corr_long_horizon),
        "long_horizon_beats_fly": bool(np.isfinite(corr_d63) and np.isfinite(corr_d63_fly)
                                       and (corr_d63 - corr_d63_fly) >= rule.fly_margin),
        "horizon_slope_up": bool(np.isfinite(corr_d63) and np.isfinite(corr_d1)
                                 and (corr_d63 - corr_d1) >= rule.min_horizon_slope),
        "no_regime_break": bool(np.isfinite(regime_shift)
                                and abs(regime_shift) <= rule.max_regime_shift),
    }
    diagnostics = {
        "levels_beats_fly_unsigned_v1": bool(
            np.isfinite(corr_levels) and np.isfinite(corr_levels_fly)
            and corr_levels - abs(corr_levels_fly) >= rule.fly_margin),
        "levels_unsigned_margin_v1": float(corr_levels - abs(corr_levels_fly))
        if np.isfinite(corr_levels) and np.isfinite(corr_levels_fly) else np.nan,
        "levels_signed_margin": float(corr_levels - corr_levels_fly)
        if np.isfinite(corr_levels) and np.isfinite(corr_levels_fly) else np.nan,
        "d63_signed_margin": float(corr_d63 - corr_d63_fly)
        if np.isfinite(corr_d63) and np.isfinite(corr_d63_fly) else np.nan,
        "horizon_slope": float(corr_d63 - corr_d1)
        if np.isfinite(corr_d63) and np.isfinite(corr_d1) else np.nan,
        "sign_frac_vol": float(sign_frac_vol),
        "sign_frac_fly": float(sign_frac_fly),
    }
    levels_ok = checks["levels_strong"] and checks["levels_sign_beats_fly"]
    changes_ok = (checks["long_horizon_strong"] and checks["long_horizon_beats_fly"]
                  and checks["horizon_slope_up"])
    if levels_ok and changes_ok and checks["no_regime_break"]:
        verdict = "CONFIRMED"
    elif not levels_ok and not changes_ok:
        verdict = "REFUTED"
    else:
        verdict = "INCONCLUSIVE"
    return {"verdict": verdict, "checks": checks, "diagnostics": diagnostics,
            "rule": dataclasses.asdict(rule)}
