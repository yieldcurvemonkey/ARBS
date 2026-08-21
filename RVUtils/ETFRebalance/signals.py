"""The signal family: what an ETF's own book might say about which bond it must buy.

Every signal here is a map ``(date, cusip) -> score``, with one sign convention that is
never varied: **a higher score is a stronger reason to BUY the bond** -- to expect it to
richen against its maturity neighbours. Fixing that at the source means the search is
about which signal expresses the view, never about which sign to use, and a signal that
only works upside-down shows up as a negative weight rather than hiding in a flag.

The four channels, and what each one claims
-------------------------------------------
**Allocation.** The fund's weight in a bond against the index weight it is benchmarked
to. A large negative active weight is a position the fund must eventually close by
buying. This is the user's original ladder idea, made benchmark-relative: a bucket that
is light because the Treasury stopped issuing into it is *not* a dislocation, and a
z-score of the fund's raw weight cannot tell the two apart.

**Flow.** What the fund actually traded, from the day-on-day change in par per share.
This is the only channel that observes a *realised* transaction rather than inferring a
future one, and its sign is genuinely ambiguous -- price impact says follow, inventory
says fade -- so ``flow`` is offered unsigned and the grid decides.

**Scarcity.** What share of a bond's publicly held float the ETF complex owns. High
ownership means less bond available to the rest of the market, which is a richness story
with no rebalance in it at all.

**Calendar.** Deletion and addition dates implied by the index rules. These need **no
holdings data whatsoever** -- they are computable from the reference data and the
published methodology -- which is exactly why they are here. They are the null the
holdings channels must beat. If ``deletion`` alone earns what ``active_w`` earns, then
the 20,000-request scrape bought nothing and the honest report says so.

What is deliberately absent
---------------------------
There is no signal that reads a bond's own price history. Momentum and mean reversion in
the richness residual are real and have nothing to do with ETFs; including them would let
the grid find a known effect and credit it to this dataset. ``resid`` is available as an
explicit *control*, to be run alongside and subtracted, not blended in silently.
"""

from __future__ import annotations

from typing import Callable, Dict, Mapping, Optional

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ standardisation


def cross_sectional_z(s: pd.Series, dates: pd.Series, *, robust: bool = True) -> pd.Series:
    """z within each date, with a scale ladder for sparse signals.

    Robust by default: one dislocated bond should not set the scale by which its own
    dislocation is judged.

    The ladder matters and is not defensive coding. A signal that is zero for most of
    the cross-section -- ``deletion`` fires on 2.05% of bond-days, ``not_held`` on almost
    none -- has a **median absolute deviation of exactly zero**, so a pure MAD z-score is
    NaN on every date. Measured: ``deletion`` produced a usable cross-section on
    **0 of 2,528 dates** and was silently dropped from the first IC pass as "too few
    finite values". The signal was fine; the standardiser was wrong for its shape. Fall
    back MAD -> standard deviation -> plain demeaning, so a sparse signal is scaled
    differently rather than deleted.
    """
    g = s.groupby(dates)
    med = g.transform("median")
    if robust:
        scale = (s - med).abs().groupby(dates).transform("median") * 1.4826
    else:
        med = g.transform("mean")
        scale = g.transform("std")
    sd = g.transform("std")
    scale = scale.where(scale > 0, sd)
    return (s - med) / scale.replace(0.0, np.nan)


def time_series_z(
    frame: pd.DataFrame, col: str, *, lookback: int, min_periods: Optional[int] = None
) -> pd.Series:
    """z of each CUSIP against its OWN trailing history, strictly backward-looking.

    ``shift(1)`` before the rolling window, so the observation being scored is never
    inside the mean and standard deviation it is scored against. Without it a one-day
    spike deflates its own z by contributing to the scale, and the effect is largest
    exactly where the signal claims to be strongest.
    """
    mp = min_periods if min_periods is not None else max(20, lookback // 4)
    g = frame.sort_values(["cusip", "date"]).groupby("cusip")[col]
    prior = g.shift(1)
    mu = prior.groupby(frame.sort_values(["cusip", "date"])["cusip"]).transform(
        lambda x: x.rolling(lookback, min_periods=mp).mean())
    sd = prior.groupby(frame.sort_values(["cusip", "date"])["cusip"]).transform(
        lambda x: x.rolling(lookback, min_periods=mp).std())
    z = (frame.sort_values(["cusip", "date"])[col] - mu) / sd.replace(0.0, np.nan)
    return z.reindex(frame.index)


# ------------------------------------------------------------------ the signals
#
# Each takes the joined active-weight frame and returns a raw (unstandardised) score
# with the BUY-IS-POSITIVE convention already applied. Standardisation happens once, in
# :func:`combine`, so components are comparable before they are weighted.


def sig_active_w(df: pd.DataFrame, **kw) -> pd.Series:
    """Underweight now -> the fund has buying to do. Negative active weight scores high."""
    return -df["active_w"]


def sig_active_rel(df: pd.DataFrame, **kw) -> pd.Series:
    """Active weight as a fraction of the index weight.

    A 20bp gap in a bond carrying 5% of the index is a rounding error; the same 20bp in
    one carrying 0.4% is half the position. The relative form says which.
    """
    return -(df["active_w"] / df["w_i"].replace(0.0, np.nan))


def sig_active_chg(df: pd.DataFrame, *, window: int = 5, **kw) -> pd.Series:
    """Where the active weight is *going*, not where it is.

    A fund that has been drifting underweight for a week is in the middle of a decision;
    one that has been underweight for a year has made it.
    """
    d = df.sort_values(["cusip", "date"])
    chg = d.groupby("cusip")["active_w"].diff(window)
    return (-chg).reindex(df.index)


def sig_flow(df: pd.DataFrame, *, window: int = 5, **kw) -> pd.Series:
    """What the fund actually bought, per ETF share, over the last ``window`` days.

    Positive = the fund has been buying. Whether that predicts richening (impact) or
    cheapening (the flow is done and the price gives it back) is the question, so the
    sign is left to the component weight rather than asserted here.
    """
    d = df.sort_values(["cusip", "date"])
    chg = d.groupby("cusip")["par_per_share"].diff(window)
    # Scale by the bond's float so a big issue's big flow is not automatically the
    # biggest signal on the board.
    return (chg / d["free_float"].replace(0.0, np.nan) * 1e6).reindex(df.index)


def sig_ownership(df: pd.DataFrame, **kw) -> pd.Series:
    """Share of publicly held float this fund owns. Scarcity -> rich, so positive."""
    return df["ownership"]


def sig_ownership_chg(df: pd.DataFrame, *, window: int = 21, **kw) -> pd.Series:
    d = df.sort_values(["cusip", "date"])
    return d.groupby("cusip")["ownership"].diff(window).reindex(df.index)


def sig_bucket_active(df: pd.DataFrame, *, width_y: float = 0.25, **kw) -> pd.Series:
    """The user's risk ladder: active weight aggregated into a constant-maturity bucket.

    Per-CUSIP active weight is noisy because a sampling fund substitutes freely between
    two bonds three months apart -- it holds the one that was cheap to source, and which
    of the pair that was carries no information. Aggregating to the bucket removes that
    substitution noise and leaves the fund's exposure to the *maturity slot*, which is
    the quantity the index rule actually pins down.

    Every CUSIP in a bucket receives the bucket's score, so the selection rule then picks
    between them on liquidity rather than on a difference that is not there.
    """
    b = np.floor(df["ttm"] / max(1e-9, width_y))
    tot_f = df.groupby([df["date"], b])["w_f"].transform("sum")
    tot_i = df.groupby([df["date"], b])["w_i"].transform("sum")
    return -(tot_f - tot_i)


def sig_bucket_hist_z(df: pd.DataFrame, *, width_y: float = 0.25,
                      lookback: int = 250, **kw) -> pd.Series:
    """The literal form of the original idea: a bucket's weight against its OWN history.

    Kept separate from :func:`sig_bucket_active` because the two make different claims
    and the difference is the whole reason the benchmark work was done. This one says
    "this bucket is lighter than it usually is". That is true of every bucket the
    Treasury has stopped issuing into, and of every bucket whose bonds have rolled down
    towards the deletion boundary -- neither of which is a dislocation the manager will
    close. It is scored anyway, because the honest comparison is against the version the
    idea was originally stated in, not only against the improved one.
    """
    b = np.floor(df["ttm"] / max(1e-9, width_y))
    w = df.groupby([df["date"], b])["w_f"].transform("sum")
    tmp = pd.DataFrame({"date": df["date"], "bucket": b, "w": w})
    tmp = tmp.sort_values(["bucket", "date"])
    prior = tmp.groupby("bucket")["w"].shift(1)
    mu = prior.groupby(tmp["bucket"]).transform(
        lambda x: x.rolling(lookback, min_periods=max(20, lookback // 4)).mean())
    sd = prior.groupby(tmp["bucket"]).transform(
        lambda x: x.rolling(lookback, min_periods=max(20, lookback // 4)).std())
    z = ((tmp["w"] - mu) / sd.replace(0.0, np.nan)).reindex(df.index)
    return -z


def sig_not_held(df: pd.DataFrame, **kw) -> pd.Series:
    """In the index and not in the book at all -- the sharpest form of underweight.

    A sampling fund omits bonds on purpose, so this is a weaker claim than it looks; it
    is separated from ``active_w`` because the two are economically different statements
    and blending them hides which one is working.
    """
    return (~df["held"].fillna(False)).astype(float) * df["w_i"].fillna(0.0)


# --- calendar-only. These read no holdings file and are the null, not the thesis. ---


def _month_end(dates: pd.Series) -> pd.Series:
    return dates + pd.offsets.MonthEnd(0)


def sig_deletion(df: pd.DataFrame, *, band_low: float, horizon_m: int = 3, **kw) -> pd.Series:
    """Bonds the index must DROP at a rebalance inside the horizon. Negative -- sell.

    A bond is dropped when its remaining maturity falls below the band's lower edge as
    measured at a month-end reconstitution. The score ramps up as that date approaches,
    so "three months out" and "three days out" are not treated as the same event.
    """
    me = _month_end(df["date"])
    months = np.arange(0, horizon_m + 1)
    hit = pd.Series(np.nan, index=df.index)
    for m in months[::-1]:
        rebal = me + pd.offsets.MonthEnd(int(m))
        ttm_at = df["ttm"] - (rebal - df["date"]).dt.days / 365.25
        drops = ttm_at < band_low
        hit = hit.mask(drops, float(m))
    # nearest rebalance that drops it -> strongest; never dropped -> 0
    return -(horizon_m + 1 - hit).fillna(0.0) / (horizon_m + 1)


def sig_addition(df: pd.DataFrame, *, band_high: float = np.inf,
                 horizon_m: int = 3, **kw) -> pd.Series:
    """Recently issued bonds that the index has just taken in, or is about to. Positive."""
    if "issue_date" not in df.columns:
        return pd.Series(0.0, index=df.index)
    age_m = (df["date"] - df["issue_date"]).dt.days / 30.44
    return np.exp(-age_m / max(1e-9, horizon_m)).where(age_m >= 0, 0.0).fillna(0.0)


def sig_month_end(df: pd.DataFrame, *, window: int = 3, **kw) -> pd.Series:
    """Proximity to the reconstitution date. A pure timing overlay, no cross-section.

    Included so that the grid can separate "this signal works" from "this signal is on
    at month-end and month-end is when the long end moves", which a prior ARBS study
    measured directly: the seasoned issue richens against the current on month-end day
    with a pooled t of 3.96 across seven tenors and 16 of 17 years positive.
    """
    dte = (_month_end(df["date"]) - df["date"]).dt.days
    return (dte <= window).astype(float)


# --- control, not a thesis ---


def sig_resid(df: pd.DataFrame, **kw) -> pd.Series:
    """The bond's own richness against the local curve. Cheap (positive residual) = buy.

    A CONTROL. Cash-UST richness mean reverts for reasons that have nothing to do with
    ETFs, so this is here to be run alongside and partialled out -- never to be blended
    in and credited to the holdings data.
    """
    return df["resid_bp"]


REGISTRY: Dict[str, Callable[..., pd.Series]] = {
    "active_w": sig_active_w,
    "active_rel": sig_active_rel,
    "active_chg": sig_active_chg,
    "bucket_active": sig_bucket_active,
    "bucket_hist_z": sig_bucket_hist_z,
    "flow": sig_flow,
    "ownership": sig_ownership,
    "ownership_chg": sig_ownership_chg,
    "not_held": sig_not_held,
    "deletion": sig_deletion,
    "addition": sig_addition,
    "month_end": sig_month_end,
    "resid": sig_resid,
}

#: Signals computable without a single holdings document. The calendar null: if these
#: earn what the holdings signals earn, the scrape bought nothing.
CALENDAR_ONLY = frozenset({"deletion", "addition", "month_end"})

#: Signals that read the fund's book.
HOLDINGS_BASED = frozenset({"active_w", "active_rel", "active_chg", "bucket_active",
                            "bucket_hist_z", "flow", "ownership", "ownership_chg",
                            "not_held"})

#: Constant across the cross-section on any given date, so they cannot be ranked against
#: each other and must never enter a cross-sectional z. They are TIMING overlays -- use
#: them through ``timing.entry_window``, not through ``signal.components``.
TIMING_ONLY = frozenset({"month_end"})


def combine(
    df: pd.DataFrame,
    components: Mapping[str, float],
    *,
    z_mode: str = "cross_section",
    z_lookback: int = 250,
    robust_z: bool = True,
    smooth_days: int = 1,
    signal_kwargs: Optional[Mapping[str, Mapping]] = None,
) -> pd.DataFrame:
    """Build every named component, standardise, weight and sum.

    Each component is standardised **before** weighting so a weight means what it says.
    Without that, ``active_w`` (order 1e-3) and ``ownership`` (order 1e-1) enter a
    weighted sum in a ratio set by their units rather than by the intent of the weights,
    and a 50/50 blend is really 99/1.
    """
    sk = dict(signal_kwargs or {})
    out = df.copy()
    parts, names = [], []

    for name, weight in components.items():
        if weight == 0:
            continue
        fn = REGISTRY.get(name)
        if fn is None:
            raise KeyError(f"Unknown signal {name!r}. Known: {sorted(REGISTRY)}")
        raw = fn(out, **sk.get(name, {}))
        out[f"raw_{name}"] = raw

        if z_mode in ("cross_section", "both"):
            z = cross_sectional_z(raw, out["date"], robust=robust_z)
        else:
            z = raw
        if z_mode in ("time_series", "both"):
            tmp = out.assign(_v=z if z_mode == "both" else raw)
            z = time_series_z(tmp, "_v", lookback=z_lookback)
        # A z-score is not bounded, and an unbounded score turns one bond into the whole
        # book on the day its denominator collapses.
        z = z.clip(-5.0, 5.0)
        out[f"z_{name}"] = z
        parts.append(z * float(weight))
        names.append(name)

    if not parts:
        raise ValueError("No signal components with a non-zero weight.")
    score = pd.concat(parts, axis=1).sum(axis=1, min_count=1)

    if smooth_days > 1:
        d = out.assign(_s=score).sort_values(["cusip", "date"])
        score = d.groupby("cusip")["_s"].transform(
            lambda x: x.rolling(smooth_days, min_periods=1).mean()).reindex(out.index)

    out["score"] = score
    out["score_components"] = ",".join(names)
    return out
