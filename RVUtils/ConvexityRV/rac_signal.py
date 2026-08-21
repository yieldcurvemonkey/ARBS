r"""Risk-adjusted carry on ultra-long forward curve pairs — the workflow-4 signal.

The brief names **risk-adjusted carry** as this book's dominant driver, and Citi
prints exactly that screen: *Taking profits on delta-hedged 15y5y/20y10y
flatteners*, close 2019-12-04, fifteen USD pairs by eight columns, with the
decision statistic being *"the ratio of the daily breakeven — the daily move in
rates that yields a convexity gain offsetting a negative daily carry — to
realized daily volatility"*.

That screen is reproduced by
:func:`RVUtils.ConvexityRV.strat3_strikeless_vol.screen_frame`. What this module
adds is the step from a screen to a **rule**, and two measurements forced its
shape.

Why the published statistic is not the traded one
-------------------------------------------------
**1. The level does not transfer, only the rank.** Graded on the 2019-12-04
table — 120 cells the code was never fitted to — Spearman against Citi is 0.986
(level), 0.944 (carry), 0.992 (breakeven), **0.988 on the ratio**. But every
column carries an offset: level −0.807 bp, carry +1.101 bp, ratio −0.190. The
level offset reproduces the one ``test_citi_figure_7_levels_and_carry`` already
documents, to two decimals, seven months later — a stable curve-construction
difference, not an error.

The consequence is not cosmetic. Citi exits around a ratio of **0.8** and enters
the steepener above **1.0**; on our curve **none** of the fifteen pairs reaches
1.0. Applying her printed threshold would fire zero times, ever — reproducing
precisely the degeneracy that made strat 1 *"a permanently-on flattener, not a
timing rule"*.

**2. The published ratio is saturated.** The breakeven is truncated to zero
whenever carry is non-negative, so the ratio is exactly 0 on 44.9 % of 2022 and
**56.2 % of 2023** — and worst on the tight forward pairs the factor attribution
identified as the convexity-dominated ones (``20Yx5Y/25Yx5Y`` 54.2 %,
``15Yx5Y/20Yx5Y`` 43.5 %). A time-series percentile of a series that is flat zero
for months is undefined exactly where the rule wants to fire, because
``carry >= 0`` *is* the entry condition.

So the screen is reported in Citi's units for the tie-out, and the **traded**
statistic is the continuous one underneath it:

.. code-block:: text

    rac = carry_1y_bp / (rlzd_vol_bp * sqrt(252))

signed, smooth through zero, no truncation, and literally risk-adjusted carry.
JPM's own RAC is the same shape — expected return over a horizon divided by
annualised realised volatility. Measured: exactly zero on 0.00 % of cells, NaN
only during the 252-day trailing-vol warmup.

Two axes, because one is one-sided
-----------------------------------
Rank alone would re-create the problem it was chosen to solve: a cross-section
always has a cheapest pair, so a rank-only rule is a permanently-on
rotate-the-flattener book. The rule therefore uses:

* **cross-sectional rank** of ``rac`` on each date — *which* pair; this is the
  axis the tie-out validated; and
* **per-pair time-series percentile** of ``rac`` against its own trailing
  history — *whether*, and *which side*. This restores the two-sidedness that
  Citi gets from her absolute thresholds, without borrowing thresholds that do
  not transfer.

The universe is not uniform in this respect and the module says so rather than
averaging over it. Fraction of days with positive carry, measured 2018-2026:

======================  =========
pair family             carry > 0
======================  =========
``10Yx10Y/*``           0.9-2.9 %
``15Yx10Y/*``           23.8-43.1 %
``15Yx5Y/*``            26.6-46.0 %
``20Yx5Y/*``            31.1-54.2 %
======================  =========

The ``10Yx10Y`` family is **structurally one-sided** on this sample: a rule
keyed on carry can only ever say "flattener" for it. It is retained and reported,
not silently traded as though two-sided.

Everything here is lagged. The signal on date *t* is built from information
through *t−1*; :func:`build_signal_panel` shifts before it ranks, so a caller
cannot forget.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "BUSINESS_DAYS",
    "ONE_SIDED_FAMILY",
    "RacConfig",
    "add_rac",
    "build_signal_panel",
    "carry_positive_fraction",
    "entry_state",
    "saturation_table",
    "side_ranks",
]

#: Citi's annualisation convention, and strat 3's.
BUSINESS_DAYS = 252.0

#: Pairs whose carry is positive on under 5 % of days in 2018-2026. A carry-keyed
#: rule cannot be two-sided on these; measured, not assumed.
ONE_SIDED_FAMILY: Tuple[str, ...] = (
    "10Yx10Y/15Yx15Y", "10Yx10Y/20Yx5Y", "10Yx10Y/20Yx10Y",
    "10Yx10Y/20Yx15Y", "10Yx10Y/25Yx5Y", "10Yx10Y/25Yx10Y",
)


@dataclass(frozen=True)
class RacConfig:
    """Every knob, with the reason for its default.

    ``lookback_days``
        Window for the per-pair time-series percentile of ``rac``. 756 = three
        years, matching Citi's own ``3y ZS`` column. Long enough to span a carry
        regime, short enough that the 2021-2026 backtest is not dominated by
        pre-COVID levels.
    ``enter_pct`` / ``exit_pct``
        Percentile of ``rac`` **within the pair's own trailing window**. A
        flattener is entered when risk-adjusted carry is unusually *good* for
        that pair (high percentile) and closed when it reverts to the middle.
        These replace Citi's absolute 0.8 / 1.0, which do not transfer.
    ``steepener_pct``
        The other side. Citi enters a steepener when the ratio is above 1.0,
        i.e. when convexity is expensive relative to the vol that has to pay for
        it. Here that is a low ``rac`` percentile.
    ``top_n``
        Cross-sectional width. Citi marks "three most attractive by each metric"
        in red, so 3 is her own number.
    ``min_carry_bp``
        A floor on raw carry, in bp/yr, applied *in addition* to the percentile.
        Default ``None`` -- deliberately off. The measured carry residual against
        Citi is 0.89 bp sd after removing the mean offset, which is large against
        a boundary at exactly zero, so a hard ``carry >= 0`` gate reads a coin
        flip on the pairs nearest it. Available for a sensitivity arm.
    """

    lookback_days: int = 756
    enter_pct: float = 0.80
    exit_pct: float = 0.50
    steepener_pct: float = 0.20
    top_n: int = 3
    min_carry_bp: Optional[float] = None
    business_days: float = BUSINESS_DAYS
    exclude_one_sided: bool = False
    start: dt.date = dt.date(2021, 1, 1)
    end: dt.date = dt.date(2026, 8, 20)
    pairs: Optional[Sequence[str]] = None

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["start"], d["end"] = str(self.start), str(self.end)
        return d


# ---------------------------------------------------------------------------
# The statistic
# ---------------------------------------------------------------------------
def add_rac(panel: pd.DataFrame, *, business_days: float = BUSINESS_DAYS) -> pd.DataFrame:
    """Attach ``rac`` = carry / annualised realised vol.

    ``panel`` is the output of ``strat3_strikeless_vol.screen_panel_from_legs``
    with ``add_screen_stats`` applied, i.e. carrying ``carry_1y_bp`` and
    ``rlzd_vol_bp``. Both are already in bp; ``rlzd_vol_bp`` is a **daily** vol,
    so it is annualised here and the result is unitless.

    Left as NaN where the trailing vol is not yet defined. That is a warmup, not
    a zero, and the difference matters: a zero would rank as neutral.
    """
    out = panel.copy()
    vol = out["rlzd_vol_bp"].astype(float)
    ann = vol * np.sqrt(business_days)
    out["rac"] = np.where(ann > 0, out["carry_1y_bp"].astype(float) / ann, np.nan)
    return out


def carry_positive_fraction(panel: pd.DataFrame) -> pd.Series:
    """Fraction of days each pair carries positively — the two-sidedness test."""
    g = panel.reset_index() if "pair" not in panel.columns else panel
    return (g.groupby("pair")["carry_1y_bp"]
             .apply(lambda s: float((s > 0).mean()))
             .sort_values(ascending=False))


def saturation_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Why the published ratio is not the traded statistic, per year.

    Reported rather than argued: a reader should be able to see the truncation
    for themselves on whatever sample they are looking at.
    """
    g = panel.reset_index() if "pair" not in panel.columns else panel.copy()
    g = g.copy()
    g["year"] = pd.to_datetime(g["date"]).dt.year
    rows = []
    for y, sub in g.groupby("year"):
        rows.append({
            "year": int(y),
            "cells": len(sub),
            "carry>=0": float((sub["carry_1y_bp"] >= 0).mean()),
            "be_truncated_to_0": float((sub["be_daily_analytic"] == 0).mean()),
            "rac_nan": float(sub["rac"].isna().mean()) if "rac" in sub else np.nan,
            "rac_exactly_0": float((sub["rac"] == 0).mean()) if "rac" in sub else np.nan,
        })
    return pd.DataFrame(rows).set_index("year")


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------
def build_signal_panel(panel: pd.DataFrame, cfg: RacConfig = RacConfig()) -> pd.DataFrame:
    """``(date, pair)`` panel carrying the lagged, ranked, percentiled signal.

    **Everything is shifted before it is used.** The columns named ``*_lag`` are
    built from information through ``t-1``; the cross-sectional rank and the
    time-series percentile are both computed on the lagged series, so a caller
    cannot accidentally rank on same-day information. This is the house rule --
    *"Lag it. Entry uses t-1 information."* -- enforced in one place.
    """
    df = panel.reset_index() if "pair" not in panel.columns else panel.copy()
    df["date"] = pd.to_datetime(df["date"])
    if cfg.pairs:
        df = df[df["pair"].isin(cfg.pairs)]
    if cfg.exclude_one_sided:
        df = df[~df["pair"].isin(ONE_SIDED_FAMILY)]
    df = df.sort_values(["pair", "date"])

    if "rac" not in df.columns:
        df = add_rac(df, business_days=cfg.business_days)

    # --- lag, per pair, before anything reads it -----------------------------
    g = df.groupby("pair", sort=False)
    df["rac_lag"] = g["rac"].shift(1)
    df["carry_lag"] = g["carry_1y_bp"].shift(1)
    df["level_lag"] = g["level_bp"].shift(1)
    df["be_over_rv_lag"] = g["be_over_rv"].shift(1) if "be_over_rv" in df else np.nan

    # --- axis 1: per-pair time-series percentile of the lagged statistic ------
    def _pct(s: pd.Series) -> pd.Series:
        return s.rolling(cfg.lookback_days, min_periods=max(60, cfg.lookback_days // 4)) \
                .rank(pct=True)

    df["rac_pct"] = df.groupby("pair", sort=False)["rac_lag"].transform(_pct)

    # --- axis 2: cross-sectional rank, WITHIN each side ----------------------
    #
    # Ranking raw `rac` across the whole cross-section looks like Citi's screen
    # ("three most attractive by each metric in red") but does not behave like a
    # second axis here, and the measurement is unambiguous. Pair-level rac
    # differs systematically -- the 10Yx10Y family carries persistently worse
    # than the 15Yx5Y family -- so an unconditional rank is nearly constant per
    # pair, and the *side* ends up decided by which pair it is rather than by
    # when. Measured on 2021-2026 with an unconditional rank:
    #
    #     10Yx10Y/20Yx15Y   steepener 66.5% of days, flattener 0.1%
    #     10Yx10Y/25Yx10Y   steepener 64.6%,         flattener 0.0%
    #     15Yx5Y/25Yx5Y     flattener 16.4%,         steepener 0.0%
    #
    # which is the same degeneracy the two-axis design exists to avoid, wearing
    # a cross-sectional hat. So the rank is computed among the pairs that
    # already qualify on the timing axis: the percentile decides *whether and
    # which side*, the rank decides *which pair*, and neither can stand in for
    # the other.
    # The within-side ranks are NOT computed here, and that is deliberate. They
    # depend on the entry thresholds, and a panel that bakes a threshold in is a
    # trap for a grid search: sweeping `enter_pct` while reusing one panel would
    # silently apply the panel's threshold and the sweep's, and the two would
    # disagree. The first draft did exactly that and the suite caught it -- a
    # rank-only config and the real config produced identical books because both
    # were filtered by the panel's mask. Everything threshold-dependent lives in
    # `entry_state`, so the panel is a function of the data and the lookback
    # only.
    #
    # Kept for reporting and for the Citi-style screen, not used by the rule.
    df["rac_xrank"] = df.groupby("date")["rac_lag"].rank(ascending=False, method="min")
    df["n_pairs_today"] = df.groupby("date")["rac_lag"].transform(lambda s: s.notna().sum())

    return df.set_index(["date", "pair"]).sort_index()


def entry_state(signal: pd.DataFrame, cfg: RacConfig = RacConfig()) -> pd.Series:
    """``+1`` flattener, ``-1`` steepener, ``0`` flat — per ``(date, pair)``.

    A flattener needs **both** axes: risk-adjusted carry unusually good for this
    pair by its own history (``rac_pct >= enter_pct``) *and*, among the pairs
    that clear that bar today, one of the best ``top_n``. The percentile decides
    *whether and which side*; the rank decides *which pair*. Neither stands in
    for the other, which is what stops the book being permanently on.

    The steepener is the mirror: ``rac_pct <= steepener_pct`` and among the
    ``top_n`` worst of the pairs clearing *that* bar. Citi takes that side when
    her ratio exceeds 1.0.

    ``exit_pct`` is not applied here — it is a position-level rule, not a
    cross-sectional one, and belongs to whatever runs the book.
    """
    df = signal
    dates = df.index.get_level_values("date")

    flat_cand = df["rac_pct"] >= cfg.enter_pct
    steep_cand = df["rac_pct"] <= cfg.steepener_pct

    rank_in_flat = (df["rac_lag"].where(flat_cand)
                    .groupby(dates).rank(ascending=False, method="min"))
    rank_in_steep = (df["rac_lag"].where(steep_cand)
                     .groupby(dates).rank(ascending=True, method="min"))

    flat_ok = flat_cand & (rank_in_flat <= cfg.top_n)
    steep_ok = steep_cand & (rank_in_steep <= cfg.top_n)

    if cfg.min_carry_bp is not None:
        flat_ok &= df["carry_lag"] >= cfg.min_carry_bp
        steep_ok &= df["carry_lag"] < cfg.min_carry_bp

    state = pd.Series(0, index=df.index, dtype=int)
    state[flat_ok.fillna(False)] = 1
    state[steep_ok.fillna(False)] = -1
    return state.rename("state")


def side_ranks(signal: pd.DataFrame, cfg: RacConfig = RacConfig()) -> pd.DataFrame:
    """The within-side ranks ``entry_state`` uses, exposed for reporting.

    Recomputed from *cfg* rather than read off the panel, for the reason given
    in :func:`build_signal_panel`.
    """
    dates = signal.index.get_level_values("date")
    return pd.DataFrame({
        "rank_in_flat": (signal["rac_lag"].where(signal["rac_pct"] >= cfg.enter_pct)
                         .groupby(dates).rank(ascending=False, method="min")),
        "rank_in_steep": (signal["rac_lag"].where(signal["rac_pct"] <= cfg.steepener_pct)
                          .groupby(dates).rank(ascending=True, method="min")),
    }, index=signal.index)
