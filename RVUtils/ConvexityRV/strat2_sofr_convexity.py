"""Citi's STIR-futures convexity-adjustment screen, ported ED -> SFR, with the
2s5s10s butterfly hedge.

The source is Citi Research's *"convexity adjustments for 1y packs"* screen, run
on Eurodollars from 2016 to 2020 and **restated by Citi itself for SOFR** in
*Rates Vol Lab - Forward steepener and vol divergence*, 12-Jun-2023, Figure 58.
The methodology note, verbatim (SOFR version):

    "Convexity adjustments for 1y SOFR packs are computed as the spread between
     the pack's rate (the average of 4 SOFR rates in the pack) and
     matched-maturity forward 1y CME swap rate. The model for convexity
     adjustment is the Ho-Lee model calibrated to cap/floor vols. Implied vol is
     calculated by matching the model to the observed convexity adjustment.
     Realized vol is 3m realized vol of the corresponding pack. For each
     valuation metric, we mark three best short convexity trades in bold."

and the trade, verbatim (13-Jan-2017 / 09-Feb-2017):

    "Sell $100k DV01 of Blues convexity adjustment, i.e. buy 1000 of H0-Z0 packs
     (1000 of each of the four contracts) and pay $1bn on a matched-maturity
     (3/18/20-3/17/21) CME swap."
    "Pay the belly of the 2s5s10s swap fly with notional weights
     $79mn/-$44.4mn/$10.9mn (0.73/-1/0.46 DV01 weights)."
    "3y1y vol is mostly driven by expectations of monetary policy, and therefore
     should be directional with the valuations of 5s on the curve. ... selling
     the 2s5s10s fly as a hedge has the advantage of positive carry, unlike
     buying volatility."


THE LEVEL OFFSET, STATED UP FRONT
---------------------------------
Citi's swap leg is **CME-cleared**. ``USD-SOFR-1D`` in this repo is not. On
2023-06-09, reproducing Citi's Figure 58 with Barchart SR3 settles against
``USD-SOFR-1D`` gives a **correlation of levels of 0.968** against Citi's 13
published rows -- the shape is reproduced -- but a **level offset of about
-3.9bp** (mean -3.89, median -4.31, range -0.86 .. -5.66) *when the matched swap
is built at the curve spec's default frequency*.

**That offset was payment frequency, not a clearing basis.** Citi specifies the
matched swap verbatim -- *"both fixed and floating legs of this swap have a
quarterly payment frequency"* -- while the ``usd_irs`` spec carried by
``USD-SOFR-1D`` quotes **annual** fixed (``rl.defaults.spec['usd_irs']`` has
``frequency: 'a'``). At a ~3.2% rate the compounding difference is about
``3q^2/8`` ~ 3.8bp, the same order as the adjustment being measured, and the
measured offset scales with the rate level exactly as compounding predicts.
Rebuilding the swap quarterly/quarterly collapses it:

==============================  ==================  ==============
matched swap                    mean error vs Citi  median error
==============================  ==================  ==============
spec default (annual fixed)          -3.89 bp          -4.31 bp
**quarterly / quarterly**            **-0.11 bp**      **-0.58 bp**
==============================  ==================  ==============

So the swap leg now goes through
:func:`RVUtils.ConvexityRV.curve_ops.matched_forward_swap_rate`, which defaults
to Q/Q; ``tests/test_convexity_rv_matched_swap.py`` keeps the annual variant as
a negative control so a regression cannot quietly put the 4bp back.

(An earlier reading of this offset attributed it to CME-vs-LCH clearing. The
measurement above rules that out -- SOFR CCP basis is sub-basis-point, and a
clearing basis would not scale with the rate level.)

**One inconsistency, recorded rather than hidden.** The *measured* adjustment now
uses the Q/Q swap, but the swap leg that is actually *traded* in the backtest is
built as an ``IRSwapQuery`` and therefore still prices at the curve spec's
annual-fixed convention. The two differ by ~3.8bp in the par rate, which sets the
traded leg's fixed coupon and so shifts its NPV by a constant; it does not change
the P&L *path*, and the measured backtest totals were identical before and after
the frequency fix (+$3,209,018 unhedged / +$1,264,288 hedged), which is the
empirical confirmation. Aligning the traded leg would need a quarterly variant of
the query-level swap builder and is left undone deliberately.

:attr:`Strat2Config.ca_basis_bp` survives, default ``0.0``, for any *genuine*
residual a user wants to apply; it is added to the raw computed CA. Nothing is
silently fudged to match Citi. The strategy is in any case driven off the
**basis-robust** metrics -- CA z-scores, the dislocation to the fitted model and
its z-scores, and the 3m roll -- four of Citi's six ranking families being
differences or z-scores and therefore invariant to a constant level shift.


THE HO-LEE MODEL AND THE ONE GENUINELY UNSPECIFIED DEGREE OF FREEDOM
--------------------------------------------------------------------
The adjustment formula was recovered empirically from eight published Citi
tables (see :mod:`RVUtils.ConvexityRV.holee` and
``tests/test_convexity_rv_holee.py``)::

    CA_pack (bp) = 0.5 * sigma^2 * mean_i(T1_i^2) * 1e4

with ``T1_i`` the ACT/365 year fraction from the as-of date to contract *i*'s
IMM date. Inverting it for the observed CA reproduces Citi's *Implied Vol*
column to a median ratio of 0.9973 on the SOFR table (13/13 rows).

What the corpus never states is how ``sigma`` itself is set. All eight reports
say only *"the Ho-Lee model calibrated to cap/floor vols"* -- no cap tenor, no
strike, no stripping method, no term-structure treatment. **This is the single
largest unspecified degree of freedom in the port**, so it is a documented,
configurable choice here rather than a hidden constant:

``sigma_model_mode="fit"`` (default)
    Fit a smooth term structure of variance across packs to the *observed* CA
    curve on each date. Writing ``x_p = 0.5 * M_p / 1e4`` (so ``CA_p = x_p *
    sigma_p^2`` with sigma in bp/yr), the model is linear in its coefficients::

        CA_model_p = x_p * (c0 + c1*T_p + c2*T_p^2)

    solved by ordinary least squares across the ranked packs, with the fitted
    variance clipped at zero. ``sigma_model_p = sqrt(v_p)``.

    **Limitation, stated plainly.** Because the model is fitted to the same
    cross-section it is then compared against, ``vs_model`` is a *residual* and
    is centred on ~zero across packs by construction. Citi's ``Vs Model`` column
    is a dislocation against an *externally* calibrated cap/floor surface and
    can therefore carry a systematic level and slope (on 6/9/23 it rises
    monotonically from +1.09 to +7.79bp). **This implementation cannot and does
    not reproduce that column's level.** What it does measure is the
    cross-sectional shape dislocation -- which pack is rich *relative to the
    smooth CA term structure of that same day* -- and the time series of that
    residual, whose z-score is the tradeable signal. Do not read ``vs_model``
    here as Citi's number.

``sigma_model_mode="external"``
    Supply your own vol term structure -- a cap/floor or swaption-implied
    ``sigma_bp`` per (date, pack) -- through ``external_sigma``. This is the
    faithful reading of *"calibrated to cap/floor vols"* and restores a model
    with an absolute level, at the cost of needing a surface this repo does not
    ship a stripped version of.

``sigma_model_mode="constant"``
    A single flat ``sigma_constant_bp`` for every pack and date. Diagnostic
    only; it makes ``vs_model`` a pure restatement of the CA curve's shape.


THE TRADE
---------
"Short convexity" = **buy the futures pack + pay fixed on the matched-maturity
1y swap, DV01-neutral**. The futures leg's DV01 is rate-invariant ($25/bp/
contract, forever); the swap leg's DV01 rises as rates fall. Holding the linear
instrument against the convex one is net short convexity, i.e. short vol, which
is why the CA is a vol-driven quantity in the first place. You profit if the CA
narrows::

    CA_DV01      = n_packs * 4 * $25                     (1000 packs = $100k/bp)
    swap         = pay fixed, IMM(k) .. IMM(k)+1y, bpv = +CA_DV01
    futures      = buy n contracts of each of the four legs
    P&L          = -CA_DV01 * d(CA)   to first order, plus the convexity the
                   swap leg's repricing actually carries

The hedge is **not** DV01-matched to the CA leg. It is sized to the regression
beta::

    regress CA(bp) on (r2y, r5y, r10y) in percent, trailing window
        CA_fit = a + b2*r2 + b5*r5 + b10*r10
        beta = b5;   w2 = -b2/beta;   w10 = -b10/beta
    belly_DV01 = CA_DV01 * beta / 100          (/100 converts % -> bp)
    wings      = w2 * belly_DV01,  w10 * belly_DV01

reproducing Citi's published notionals to 0.996 and 0.997 on the two 2017
trades. Citi re-estimated the weights within three weeks of each other
(0.73/-1/0.47 beta 21.4 on 13-Jan-2017; 0.705/-1/0.465 beta 20.6 on
09-Feb-2017), so the **regression is implemented, not the frozen numbers**.


SIGN CONVENTIONS -- ESTABLISHED EMPIRICALLY, NOT ASSUMED
--------------------------------------------------------
* ``IRSwapQuery`` OUTRIGHT ``bpv > 0`` = **payer** (gains when rates rise).
* ``IRSwapQuery`` FLY ``bpv > 0`` constrains the **belly** and = **pay the
  belly**, receive the wings. Verified: ``risk_weights=[0.73, 1.0, 0.47]`` with
  ``bpv=+21400`` resolves to ``[-0.73, +1.0, -0.47]`` and notionals
  -$82.6mn/+$47.5mn/-$12.0mn on 2023-06-09, the same shape and magnitude as
  Citi's published $79mn/-$44.4mn/$10.9mn. **The builder mutates the
  ``risk_weights`` list in place**, so a fresh list is passed for every query.
* ``STIRFutureQuery`` OUTRIGHT ``contracts > 0`` = **long the future** = short
  the rate. Verified end-to-end through ``QueryDrivenBacktest``: 100 contracts
  of SR3M25 held 2023-06-09..2023-06-15 over a +4.50bp rate move marked
  -$11,250, exactly ``-4.50 * 25 * 100``.

Every leg of the package goes through the engine's own position handlers -- the
futures leg through ``STIRFutureHandler`` as four separate one-contract-sized
OUTRIGHT queries. Note that a *pack alias* query (``symbol="whites"``) is
**not** used: the STIR handler marks with the unweighted PV01 sum against the
risk-weighted price sum, which quadruples a 4-leg pack's P&L. Four separate
OUTRIGHT legs have no such defect and were verified numerically.


DATA COVERAGE -- WHY THE DEFAULT PACK SET STOPS AT RANK 10
-----------------------------------------------------------
Citi's SOFR table ranks pack windows 5..17 (Reds M4-H5 through Golds M7-H8).
Reproducing that *for one date* is fine -- 2023-06-09 has all 24 contracts
cached and the tie-out runs on it. Reproducing it *daily over years* is not,
because the local Barchart SR3 store is demand-driven rather than a complete
archive. Scanned directly out of the 8-shard diskcache
(``STIRFuturePricer_Cache``, 2,072 EOD dates 2018-05..2026-08), the number of
dates carrying **every** contract a pack window needs is::

    pack windows   contracts   2019  2020  2021  2022  2023  2024  2025  2026
    1..10           1..13       252   253   252   252   183     1     2     1
    4..13           4..16       252   253   252   185     3     1     2     1
    5..17 (Citi)    5..20        77   253   187    40     2     1     1     0

A cold contract costs ~60s over the network, so backfilling ~700 missing dates
x ~10 contracts is a many-hour job, not a step in a backtest.

The obvious substitute -- reading IMM x IMM forwards off the futures-calibrated
``USD-SOFR-1D-Q12STIRT`` curve, which *is* complete (2,060 dates 2018-06 to
2026-08) -- was tested and **rejected**. Against raw settles on 390 matched
(date, pack) observations the pack-level CA disagrees by a median absolute
**9.3bp in 2019** and 2.6bp in 2022, and the two CA series correlate at only
**0.33**. That is calibration residual, not convexity, and it is several times
the size of the signal.

So the defaults here are ``n_contracts=13``, ``rank_start=2``, ``n_packs=9`` --
windows 2..10, which covers Whites, Reds and Greens and runs daily from
2019-01-02 to roughly 2023-09 on cached data alone. **Blues and Golds, the
packs Citi actually traded, are out of reach offline.** All three are config
knobs: widen them on a machine whose cache has been warmed, and the code will
happily produce Citi's exact 13 rows -- as the 2023-06-09 tie-out demonstrates.
"""

from __future__ import annotations

import datetime
import math
import os
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.holee import (
    DEFAULT_CONVENTION,
    implied_vol_from_ca_bp,
    pack_ca_bp,
    pack_time_weight,
)
from RVUtils.ConvexityRV.packs import (
    DV01_PER_CONTRACT,
    PACK_COLOURS,
    contract_code,
    matched_swap_dates,
    pack_label,
    pack_t1s,
    quarterly_imm_sequence,
)

__all__ = [
    "Strat2Config",
    "PackSpec",
    "LIVE_SOURCE",
    "INTRADAY_SOURCE_MARKERS",
    "assert_settle_source",
    "pack_windows",
    "futures_symbol",
    "ca_snapshot",
    "fit_sigma_model",
    "build_panel",
    "local_cached_dates",
    "local_strip_depths",
    "trim_to_contiguous_run",
    "coverage_by_run",
    "panel_diagnostics",
    "panel_timeseries",
    "window_span_ok",
    "model_timeseries",
    "daily_screen",
    "assert_ran",
    "rank_flags",
    "select_pack",
    "hedge_regression",
    "HedgeFit",
    "hedge_sizing",
    "TradeSpec",
    "build_trade_queries",
    "plan_epochs",
    "run_backtest",
    "RANK_METRICS",
]


# ===========================================================================
# Settlement source guard
# ===========================================================================
#: The Barchart INTRADAY quote feed. Named so it can be rejected by name rather
#: than warned against in prose. It is the source ``BARCHART_STIRF_CURVE``
#: reaches for internally, so the trap is one keyword argument away at all times.
LIVE_SOURCE = "BARCHART_TOS_LIVE_STIRF-RL"

#: Substrings marking a futures source as an intraday quote feed rather than a
#: settlement mark. Matched case-insensitively.
INTRADAY_SOURCE_MARKERS: Tuple[str, ...] = ("TOS_LIVE", "_LIVE", "INTRADAY")


def assert_settle_source(source: str, *, field: str = "futures_source",
                         allow_globex_close: bool = False) -> str:
    """Raise unless *source* marks the futures leg at the CME **settlement**.

    The convexity adjustment is a difference between a futures rate and a swap
    rate **at the same instant**. Re-timing one leg does not degrade gracefully:
    it moves a difference whose whole magnitude is a few basis points, and the
    error lands entirely in the signal.

    Two sources fail that test, for different reasons.

    **An intraday quote feed** is the obvious one, and this function has always
    rejected it. Nor is there a coverage argument for it -- measured over the
    whole 12.7M-key local slice of ``BARCHART_TOS_LIVE_STIRF-RL``, its contiguous
    strip reaches depth 20 on **zero dates in every year 2018-2026**, so it cannot
    supply the deep packs it would be reached for either.

    **``BARCHART_STIRF-RL`` is the one this function used to recommend, and it is
    not a settlement source.** Measured 2026-08-26: a ``date`` request under it
    resolves to Barchart 1-minute bars picked NEAREST 17:00 ET, i.e. the 15:59 CT
    bar -- the last bar of the Globex session. It equals that bar on **24 of 27**
    (date, contract) cells (mean 0.093 bp) and the CME settle on far fewer (mean
    0.389 bp). Meanwhile ``swap_source="CITIVELO_EXCEL"`` at a ``date`` is Citi's
    daily grid, measured at **15:00 ET**. So the panel was marking its futures leg
    two hours after its swap leg: |15:59 CT - 13:59 CT| per contract runs mean
    0.81 bp, median 0.5, p90 1.5, max 4.5 -- against a pack CA of 1.3-6.8 bp.

    :data:`~MDP.STIRFutures.STIRFutureMDP.SETTLE_SOURCE` fixes that: it reads
    Barchart's daily bars, whose ``Close`` matches the 13:59 CT settle-window bar
    (mean 0.201 bp, exact on 57/69 discriminating cells) rather than the session
    close (0.907 bp, 16/69).

    ``allow_globex_close=True`` reopens the old source deliberately -- for
    reproducing a panel that was computed under it, and for nothing else. Any
    number it produces is a Globex-close mark against a 15:00 curve; say so
    wherever it is reported.
    """
    from MDP.STIRFutures.STIRFutureMDP import GLOBEX_CLOSE_SOURCE, SETTLE_SOURCE

    s = str(source)
    up = s.upper()
    if any(m in up for m in INTRADAY_SOURCE_MARKERS):
        raise ValueError(
            f"{field}={s!r} is an intraday quote feed, not a settlement source. "
            "The convexity adjustment marks a futures leg against a swap leg at "
            "the same instant; a live quote re-times one of them. Use "
            f"{SETTLE_SOURCE!r}.")
    if up == GLOBEX_CLOSE_SOURCE and not allow_globex_close:
        raise ValueError(
            f"{field}={s!r} resolves a date to the 15:59 CT bar -- the GLOBEX "
            "CLOSE, not the CME settle (measured: it equals that bar 24/27, the "
            "settle far less often). The swap leg is marked at 15:00 ET, so this "
            "re-times the futures leg by two hours, worth mean 0.81 bp / p90 1.5 "
            f"bp per contract against a 1.3-6.8 bp adjustment. Use {SETTLE_SOURCE!r}, "
            "or pass allow_globex_close=True to reproduce an old panel knowingly.")
    return s


# ===========================================================================
# Config
# ===========================================================================
#: Ranking metrics. A pack is a MORE attractive short-convexity candidate the
#: HIGHER each of these is (Citi: *"we mark three best short convexity trades in
#: bold"*, and the direction table in the note is uniformly "high").
RANK_METRICS: Tuple[str, ...] = (
    "ca_bp",             # CA outright wide
    "ca_z3m",            # CA wide vs its own 3m history
    "ca_z1y",            # CA wide vs its own 1y history
    "vs_model_bp",       # CA rich to Ho-Lee fair value
    "vs_model_z3m",      # dislocation extreme vs its own 3m history
    "vs_model_z1y",      # dislocation extreme vs its own 1y history
    "roll_3m_bp",        # short position earns rolldown as the CA slides down
    "implied_over_realized",   # CA-implied vol rich to delivered vol
)


@dataclass(frozen=True)
class Strat2Config:
    """Every knob in the strategy, documented inline.

    Defaults reproduce Citi's published screen as closely as the available data
    allows; nothing here is tuned on the backtest's own P&L.
    """

    # ---------------------------------------------------------------- market
    curve: str = "USD-SOFR-1D"
    """Swap curve for the matched-maturity leg, the 2s5s10s fly and all par
    rates. NOT CME-cleared -- see the module docstring on ``ca_basis_bp``."""

    swap_source: str = "CITIVELO_EXCEL"
    """``IRSwapsMDP`` source. Verified full coverage 2019-01-02..2026-08-12."""

    futures_source: str = "BARCHART_STIRF_SETTLE-RL"
    """``STIRFutureMDP`` source for SR3 settles. NB the class default is
    ``WEBULL_STIRF-RL``; this must be passed explicitly.

    Was ``BARCHART_STIRF-RL`` until 2026-08-27, which is the **Globex close**, two
    hours after this config's 15:00 ET swap leg -- see :func:`assert_settle_source`
    for the measurement. Panels built before that date carry the old mark; the
    price cache is keyed by source, so they cannot be silently mixed."""

    futures_root: str = "SR3"
    """CME root for the 3M SOFR future. ``$25.00/bp/contract``, identical to
    the 3M Eurodollar -- the one convention that ports ED->SFR unchanged."""

    # ---------------------------------------------------------------- universe
    n_contracts: int = 13
    """Quarterly contracts to pull per date, from the front IMM. 13 gives pack
    windows 1..10. Citi's SOFR table is windows 5..17, which needs 20 -- see the
    module docstring on why the local SR3 store cannot support that daily."""

    rank_start: int = 2
    """1-indexed rank of the FIRST pack window that is ranked and tradeable.
    Windows below this are still computed: window ``rank_start-1`` is what the
    3m roll of the first ranked pack is measured against, so ``rank_start`` can
    never be 1. Citi's SOFR table starts at 5 (Reds)."""

    n_packs: int = 9
    """How many consecutive pack windows to rank. Citi printed 13."""

    min_priced_contracts: int = 4
    """Fewest resolved settles a date needs before :func:`build_panel` will keep
    it. **Four -- one pack window -- and this used to be an all-or-nothing rule.**

    The line was ``if len(prices) < cfg.rank_start + cfg.n_packs + 2: continue``,
    i.e. a date had to price the *deepest requested* pack or it priced nothing at
    all. Since ``ca_snapshot`` already skips the windows it cannot quote, that
    test bought no correctness; it only threw away the near packs of any date
    whose deferred end was cold. Measured on this store: 2024 holds 252 dates
    able to quote rank 1 and 180 able to quote rank 5, and the shipped near-pack
    panel carries 19.

    Set it higher to restore the old behaviour for a specific run; the per-date
    availability is recorded on every row (``n_priced``, ``strip_depth``,
    ``max_rank_available``) either way, so what a date could NOT do is data
    rather than absence."""

    # ---------------------------------------------------------------- CA level
    ca_basis_bp: float = 0.0
    """Constant basis ADDED to the raw computed CA, in bp. Default 0.0 = report
    the raw number. Citi's swap leg is CME-cleared and this curve is not; the
    measured gap on 2023-06-09 was about -3.9bp (mean -3.89, median -4.31).
    Set this only to restate the screen on a CME basis, and say so when you do.
    It cancels out of every z-score, the roll and vs-model, so it changes the
    CA level, the implied vol and implied/realized ONLY."""

    round_pack_price_to_tick: bool = False
    """CME quotes packs to a quarter tick (0.0025). ``IRSwapValue.CVX_ADJ``
    rounds; this screen does not, because the unrounded number is what tied out
    to Citi at corr 0.968 and a quarter tick is 0.25bp of CA granularity --
    a quarter of the smallest CA in the table."""

    # ---------------------------------------------------------------- Ho-Lee
    holee_convention: str = DEFAULT_CONVENTION
    """``"citi"`` (``0.5*sigma^2*T1^2``, what the published tables use) or
    ``"hull"`` (the textbook ``0.5*sigma^2*T1*T2``, which drifts 0.933->0.975
    across Citi's 1/12/17 table and is therefore wrong for this screen)."""

    sigma_model_mode: str = "fit"
    """``"fit"`` | ``"external"`` | ``"constant"``. See the module docstring --
    this is the one genuinely unspecified degree of freedom in the port."""

    sigma_fit_degree: int = 2
    """Polynomial degree of the fitted VARIANCE term structure in T (years).
    2 = ``c0 + c1*T + c2*T^2``. Degree 1 is the robust fallback when few packs
    have finite CAs."""

    sigma_constant_bp: float = 100.0
    """Flat vol for ``sigma_model_mode="constant"``, bp/yr normal."""

    ca_floor_bp: float = 0.1
    """Below this CA the flat-sigma inversion is reported ``NaN`` rather than a
    rounding-dominated number. Citi's own 1/16/20 table prints ``n/a`` at
    CA=0.01 and CA=0.08 but a value at CA=-0.02, so the published rule is not a
    pure sign test; a small positive floor is the documented deviation."""

    # ---------------------------------------------------------------- metrics
    realized_window_days: int = 63
    """Business days in the "3m realized vol of the corresponding pack" window.
    Computed on the pack's own LABEL history, so it is constant-contract by
    construction and carries no IMM-roll jump."""

    realized_annualisation: float = 252.0
    """``sqrt(252)`` scaling of daily close-to-close pack-rate changes. Normal
    (bp/yr) vol, the same units as cap/floor vols."""

    z_window_3m: int = 63
    z_window_1y: int = 252
    """Trailing business-day windows for the two z-scores, inclusive of today.
    Sample stdev, demeaned. Window mechanics are inference -- the corpus does
    not state them."""

    week_days: int = 5
    """Lag for the "1 Week Chg" column."""

    min_history_for_z1y: int = 252
    """A label needs at least this many observations before its 1Y z-score is
    emitted. Short of it the metric is NaN and simply does not vote."""

    window_span_tolerance: float = 0.0
    """Calendar-span guard on every rolling window. ``0.0`` = OFF (legacy).

    ``rolling(252)`` counts **rows**, not days, so on a gappy panel a "1Y"
    z-score can be computed from rows spanning years. Measured on the shipped
    near-pack panel: as of 2024-01-03 the 252-row window spans **883 calendar
    days** and the 63-row window spans **532**; as of 2025-03-05 the 252-row
    window spans **1,289 days**. That was invisible only because
    :func:`trim_to_contiguous_run` deleted the gappy tail before anyone looked.

    The moment coverage is restored -- which is the whole point of the repair --
    that defect becomes live, so un-trimming without this guard would swap a
    truncated series for a silently wrong one. With a tolerance of ``t``, a
    ``w``-row window is emitted only if its rows span at most
    ``w / 252 * 365.25 * t`` calendar days; otherwise the value is ``NaN``.
    ``1.5`` is the value used by the rebuilt panels: it admits ordinary holiday
    clustering (a clean 252-row year spans ~365 days = 1.0) and rejects a window
    that has bridged a hole. Off by default so a shipped artifact still
    reproduces bit-for-bit."""

    # ---------------------------------------------------------------- ranking
    rank_metrics: Tuple[str, ...] = RANK_METRICS
    top_n_per_metric: int = 3
    """*"For each valuation metric, we mark three best short convexity trades."*"""

    min_metrics_flagged: int = 0
    """Stay flat unless the winner is flagged by at least this many metrics.
    0 = always hold the top-ranked pack, which is what Citi did (it rolled
    Blues -> Greens rather than closing the theme)."""

    # ---------------------------------------------------------------- hedge
    hedge_enabled: bool = True
    """Whether the 2s5s10s fly is part of the package. This is the DEFAULT that
    :func:`run_backtest` uses when its ``hedged`` argument is left off, so a
    hedged-vs-unhedged comparison is one config and two calls rather than two
    configs whose other thirty knobs then have to be kept in sync."""

    hedge_tenors: Tuple[str, str, str] = ("2Y", "5Y", "10Y")
    hedge_regression_days: int = 252
    """Trailing window for ``CA ~ r2y + r5y + r10y``. Citi re-estimated within
    three weeks, so this is re-fit at every entry."""

    hedge_min_abs_beta: float = 1.0
    """Skip the hedge for an epoch if ``|beta| < this`` (bp of CA per percent of
    fly). A near-zero beta makes ``w2 = -b2/beta`` explode."""

    hedge_require_positive_wings: bool = True
    """``IRSwapStructure._build_fly`` forces the wings opposite in sign to the
    belly, so a regression implying a same-sign wing cannot be expressed as a
    fly. When that happens the hedge is skipped for the epoch and recorded."""

    # ---------------------------------------------------------------- trade
    ca_dv01: float = 100_000.0
    """Dollars per bp on the CA leg. Citi's flagship was $100k (1000 packs,
    $1bn swap); the executed model-portfolio trade was $200k."""

    max_hold_months: int = 3
    """Force a re-strike after this long. Citi's realised holds were ~4 months
    (Blues 9-Feb -> 6-Jun 2017) and ~2 months (Greens 6-Jun -> 8-Aug 2017), and
    carry is quoted "over a 3m term"."""

    rebalance_freq: str = "BMS"
    """pandas offset alias for the dates the screen is consulted. ``BMS`` =
    first business day of each month. The book is only re-struck when the
    selected pack CHANGES or ``max_hold_months`` is exceeded."""

    signal_cadence: str = "W-WED"
    """Cadence at which the full screen is computed and stored for inspection.
    The PANEL (CA per pack per day) is always daily -- z-scores and realized
    vol need it -- so this only controls how often the ranked table is
    materialised."""

    cost_bp_per_roundtrip: float = 0.0
    """One optional cost knob, in bp of CA DV01 per round trip. Citi excludes
    costs explicitly (*"Calculations do not include transaction costs and other
    fees"*), so the default reproduces their convention; set it to price the
    strategy honestly."""

    # ---------------------------------------------------------------- window
    start: datetime.date = datetime.date(2019, 1, 1)
    end: datetime.date = datetime.date(2026, 8, 14)
    """Requested window. The EFFECTIVE window is data-driven: ``build_panel``
    skips any date whose futures strip or swap curve is missing, so the real
    span is whatever the panel comes back with. Report that, never this."""

    def __post_init__(self) -> None:
        if self.sigma_model_mode not in ("fit", "external", "constant"):
            raise ValueError(f"bad sigma_model_mode {self.sigma_model_mode!r}")
        assert_settle_source(self.futures_source, field="futures_source")
        if self.min_priced_contracts < 4:
            raise ValueError(
                f"min_priced_contracts={self.min_priced_contracts} cannot quote "
                "any pack; a pack window is four consecutive contracts")
        if self.window_span_tolerance < 0:
            raise ValueError("window_span_tolerance must be >= 0 (0 = off)")
        if self.rank_start < 2:
            raise ValueError("rank_start must be >= 2 so the 3m roll has a nearer pack")
        if self.rank_start + self.n_packs - 1 + 3 > self.n_contracts:
            raise ValueError(
                f"n_contracts={self.n_contracts} cannot cover packs "
                f"{self.rank_start}..{self.rank_start + self.n_packs - 1}")


# ===========================================================================
# Pack windows
# ===========================================================================
@dataclass(frozen=True)
class PackSpec:
    """One rolling 1y pack window as of a date."""

    rank: int                                   # 1-indexed position of the FIRST contract
    label: str                                  # "M6-H7"
    colour: Optional[str]                       # "Blues" when the rank lands on one
    contracts: Tuple[Tuple[int, int], ...]      # ((2026,6), (2026,9), (2026,12), (2027,3))
    symbols: Tuple[str, ...]                    # ("SR3M26", ...)
    swap_start: datetime.date
    swap_end: datetime.date
    t1s: Tuple[float, ...]                      # ACT/365 as_of -> each IMM date
    time_weight: float                          # M = mean(T1^2) under the convention
    t_mid: float                                # mean(T1), the pack's effective maturity


def futures_symbol(year: int, month: int, root: str = "SR3") -> str:
    """``(2026, 6) -> 'SR3M26'`` -- the CME/Barchart symbol."""
    return f"{root}{contract_code(year, month)[0]}{year % 100:02d}"


def pack_windows(as_of: datetime.date, cfg: Strat2Config) -> List[PackSpec]:
    """Every rolling 1y pack window from rank 1, as of *as_of*.

    Rank 1 is the pack of the four front quarterly contracts (Whites). Windows
    below ``cfg.rank_start`` are returned too: the 3m roll of the first ranked
    pack is measured against the window one contract nearer.
    """
    seq = quarterly_imm_sequence(as_of, cfg.n_contracts)
    out: List[PackSpec] = []
    for k in range(len(seq) - 3):
        cts = tuple(seq[k:k + 4])
        t1s = tuple(pack_t1s(as_of, cts))
        start, end = matched_swap_dates(cts)
        out.append(PackSpec(
            rank=k + 1,
            label=pack_label(cts[0], cts[-1]),
            colour=PACK_COLOURS.get(k + 1),
            contracts=cts,
            symbols=tuple(futures_symbol(y, m, cfg.futures_root) for y, m in cts),
            swap_start=start,
            swap_end=end,
            t1s=t1s,
            time_weight=pack_time_weight(t1s, convention=cfg.holee_convention),
            t_mid=float(np.mean(t1s)),
        ))
    return out


# ===========================================================================
# One day's raw CA snapshot
# ===========================================================================
def _swap_par_rate(pricer: Any, curve: str, *, tenor: Optional[str] = None,
                   effective_date: Optional[datetime.date] = None,
                   maturity_date: Optional[datetime.date] = None,
                   frequency: Optional[str] = "Q",
                   leg2_frequency: Optional[str] = "Q") -> float:
    """Par rate in PERCENT of one swap, priced off an already-built curve.

    Either ``tenor`` (a standard or forward tenor string) or BOTH explicit
    dates -- which are QUERY-level fields on ``IRSwapQuery``, not
    ``structure_kwargs``.

    **The matched-maturity swap is quarterly/quarterly, and that is not a
    detail.** Citi specifies it verbatim; the ``usd_irs`` spec on this curve
    quotes annual fixed, and the ~3.8bp compounding gap is the same order as the
    convexity adjustment being measured. When explicit dates are supplied -- the
    matched-swap case -- the rate is built through
    ``curve_ops.matched_forward_swap_rate`` at the requested frequency. Pass
    ``frequency=None`` to fall back to the spec default (the negative control in
    ``tests/test_convexity_rv_matched_swap.py``). See the module docstring.
    """
    if effective_date is not None and maturity_date is not None:
        from RVUtils.ConvexityRV.curve_ops import matched_forward_swap_rate

        return matched_forward_swap_rate(
            pricer, effective_date, maturity_date,
            frequency=frequency, leg2_frequency=leg2_frequency,
        )

    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.RATE,
                    curve=curve, tenor=tenor, effective_date=effective_date,
                    maturity_date=maturity_date, structure_kwargs={"bpv": 1.0})
    package, weights = q.resolve_package(pricer_or_curve=pricer)
    package = [pricer.resolve_pricable(p, w) for p, w in zip(package, weights)]
    vmap = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
    return float(vmap.apply(value=IRSwapValue.RATE))


def ca_snapshot(
    as_of: datetime.date,
    cfg: Strat2Config,
    *,
    futures_prices: Mapping[str, float],
    swap_pricer: Any,
) -> pd.DataFrame:
    """One day of the screen's RAW inputs -- everything that needs market data.

    Returns a frame indexed by pack label with the columns the time-series
    metrics are then built from. Everything downstream (z-scores, realized vol,
    roll, the model fit) is pure pandas on this panel.
    """
    rows = []
    for spec in pack_windows(as_of, cfg):
        px = [futures_prices.get(s) for s in spec.symbols]
        if any(p is None or not np.isfinite(p) for p in px):
            continue
        prices = np.asarray(px, dtype=float)
        avg_price = float(prices.mean())
        if cfg.round_pack_price_to_tick:
            avg_price = round(avg_price / 0.0025) * 0.0025
        pack_rate = 100.0 - avg_price                      # percent
        swap_rate = _swap_par_rate(swap_pricer, cfg.curve,
                                   effective_date=spec.swap_start,
                                   maturity_date=spec.swap_end)
        rows.append({
            "date": pd.Timestamp(as_of),
            "rank": spec.rank,
            "pack": spec.label,
            "colour": spec.colour,
            "swap_start": spec.swap_start,
            "swap_end": spec.swap_end,
            "pack_rate": pack_rate,
            "swap_rate": swap_rate,
            "ca_bp": (pack_rate - swap_rate) * 100.0 + cfg.ca_basis_bp,
            "time_weight": spec.time_weight,
            "t_mid": spec.t_mid,
        })
    return pd.DataFrame(rows)


# ===========================================================================
# The model sigma
# ===========================================================================
def fit_sigma_model(
    ca_bp: Sequence[float],
    time_weight: Sequence[float],
    t_mid: Sequence[float],
    *,
    degree: int = 2,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit a smooth VARIANCE term structure to one day's observed CA curve.

    ``CA_p = x_p * v_p`` with ``x_p = 0.5 * M_p / 1e4`` and ``v_p`` the Ho-Lee
    variance in ``bp^2``. Modelling ``v(T)`` as a polynomial makes the whole
    thing linear in its coefficients, so it is one ``lstsq`` and has no
    convergence behaviour to reason about::

        CA_model_p = x_p * (c0 + c1*T_p + ... + c_d*T_p^d)

    Returns ``(sigma_model_bp, ca_model_bp, coeffs)``. Fitted variance is
    clipped at zero -- in the 2019-2021 near-zero-rate regime the observed CAs
    sit close to (and sometimes below) zero and the clip does bind; that is
    reported rather than hidden, via the returned sigma being exactly 0.
    """
    ca = np.asarray(ca_bp, dtype=float)
    m = np.asarray(time_weight, dtype=float)
    t = np.asarray(t_mid, dtype=float)
    ok = np.isfinite(ca) & np.isfinite(m) & np.isfinite(t) & (m > 0)
    n_out = ca.shape[0]
    sigma = np.full(n_out, np.nan)
    ca_model = np.full(n_out, np.nan)
    deg = int(degree)
    if ok.sum() < deg + 1:
        return sigma, ca_model, np.full(deg + 1, np.nan)

    x = 0.5 * m / 1e4                                   # CA_bp = x * sigma_bp^2
    a = np.stack([x * t ** k for k in range(deg + 1)], axis=1)
    coeffs, *_ = np.linalg.lstsq(a[ok], ca[ok], rcond=None)
    v = np.clip(a @ coeffs / np.where(x != 0, x, np.nan), 0.0, None)
    sigma = np.sqrt(v)
    ca_model = x * v
    return sigma, ca_model, coeffs


def _sigma_for_day(day: pd.DataFrame, cfg: Strat2Config,
                   external: Optional[Mapping[str, float]] = None) -> pd.DataFrame:
    """Attach ``sigma_model_bp`` / ``ca_model_bp`` to one day's ranked packs.

    The two ``pack_*`` helpers in :mod:`RVUtils.ConvexityRV.holee` take the four
    ``T1_i`` and reduce them to ``M = mean(T1^2)`` internally. The panel already
    carries ``M`` as ``time_weight``, so a single pseudo-``T1`` of ``sqrt(M)``
    is passed -- ``pack_time_weight([sqrt(M)]) == M`` exactly -- rather than
    re-deriving the four dates. The tests assert that identity.
    """
    out = day.copy()
    if cfg.sigma_model_mode == "fit":
        sigma, ca_model, _ = fit_sigma_model(
            out["ca_bp"].to_numpy(float), out["time_weight"].to_numpy(float),
            out["t_mid"].to_numpy(float), degree=cfg.sigma_fit_degree)
        out["sigma_model_bp"] = sigma
        out["ca_model_bp"] = ca_model
        return out
    if cfg.sigma_model_mode == "constant":
        out["sigma_model_bp"] = float(cfg.sigma_constant_bp)
    else:                                                   # "external"
        if external is None:
            raise ValueError("sigma_model_mode='external' needs an external_sigma mapping")
        out["sigma_model_bp"] = [float(external.get(p, np.nan)) for p in out["pack"]]
    out["ca_model_bp"] = [
        pack_ca_bp(s, [math.sqrt(w)], convention=cfg.holee_convention)
        if (np.isfinite(s) and w > 0) else np.nan
        for s, w in zip(out["sigma_model_bp"], out["time_weight"])]
    return out


# ===========================================================================
# The daily panel
# ===========================================================================
def build_panel(
    dates: Sequence[datetime.date],
    cfg: Strat2Config,
    *,
    futures_mdp: Any = None,
    swaps_mdp: Any = None,
    progress: bool = True,
    _depth: int = 0,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Daily CA panel and daily hedge-rate panel.

    Returns ``(panel, rates)``:

    * ``panel`` -- long, one row per (date, pack label), carrying rank,
      ``pack_rate``, ``swap_rate``, ``ca_bp``, ``time_weight``, ``t_mid`` and
      the matched swap's dates.
    * ``rates`` -- wide, one row per date, the ``hedge_tenors`` par rates in
      percent, for the 2s5s10s regression.

    Keying by pack LABEL (not rank) is what makes the time series
    constant-contract: a label's four contracts never change, so its realized
    vol and z-scores carry no IMM-roll jump. Citi's own note flags that jump as
    the trap (*"on IMM roll dates the pack's constituent contracts change"*).

    A date with an incomplete futures strip is SKIPPED for the packs it cannot
    price rather than filled -- the Barchart EOD path already ffills/bfills
    within its own price frame, and stacking another fill on top of that would
    manufacture CA history that never printed.

    **That sentence describes what this function was always meant to do, and
    until 2026-08-19 a single line above it prevented it.** ``if len(prices) <
    cfg.rank_start + cfg.n_packs + 2: continue`` demanded the *deepest* requested
    pack before it would keep *any* pack, so a date whose deferred end was cold
    was skipped for the front packs it could price perfectly well. The floor is
    now :attr:`Strat2Config.min_priced_contracts` (4 = one window), and what each
    date could not do is written onto its rows instead of erasing the date:

    ``n_priced``            resolved settles among the requested ``n_contracts``
    ``strip_depth``         contiguous front run of those (what packs can use)
    ``max_rank_available``  deepest quotable pack window, ``strip_depth - 3``

    Sparsity is thereby visible downstream -- a reader can plot ``ca_bp`` and
    ``max_rank_available`` on the same date axis -- rather than being a hole that
    every chart then draws a straight line through.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    futures_mdp = futures_mdp or STIRFutureMDP(source=cfg.futures_source)
    swaps_mdp = swaps_mdp or IRSwapsMDP(source=cfg.swap_source)

    panel_parts: List[pd.DataFrame] = []
    rate_rows: List[Dict[str, Any]] = []
    retry: List[Any] = []
    n = len(dates)
    for i, d in enumerate(dates):
        d = d.date() if isinstance(d, (pd.Timestamp, datetime.datetime)) else d
        try:
            seq = quarterly_imm_sequence(d, cfg.n_contracts)
            syms = [futures_symbol(y, m, cfg.futures_root) for y, m in seq]
            snap = futures_mdp.get_data({"symbols": syms, "timestamp": d})
            prices: Dict[str, float] = {}
            for s in syms:
                v = snap.get(s)
                if v:
                    try:
                        p = float(v[0].price())
                        if np.isfinite(p):
                            prices[s] = p
                    except Exception:
                        pass
            # Contiguous front run -- what a pack window can actually use. A hole
            # at rank 7 does not stop ranks 1..4 from being priced, so this is
            # measured rather than assumed equal to len(prices).
            strip_depth = 0
            for s in syms:
                if s in prices:
                    strip_depth += 1
                else:
                    break
            if strip_depth < cfg.min_priced_contracts:
                continue
            pricer = swaps_mdp.get_pricer({"curve_name": cfg.curve, "timestamp": d,
                                           "offline": True})
            ref = pricer.reference_date()
            ref = ref.date() if hasattr(ref, "date") else ref
            if ref != d:
                continue
            part = ca_snapshot(d, cfg, futures_prices=prices, swap_pricer=pricer)
            if part.empty:
                continue
            part["n_priced"] = int(len(prices))
            part["strip_depth"] = int(strip_depth)
            part["max_rank_available"] = int(strip_depth - 3)
            panel_parts.append(part)
            row: Dict[str, Any] = {"date": pd.Timestamp(d)}
            for t in cfg.hedge_tenors:
                row[t] = _swap_par_rate(pricer, cfg.curve, tenor=t)
            rate_rows.append(row)
        except Exception as exc:                              # noqa: BLE001
            if progress:
                print(f"  {d}: skipped ({type(exc).__name__}: {exc})", flush=True)
            retry.append(d)
            continue
        if progress and (i + 1) % 100 == 0:
            print(f"  panel {i + 1}/{n} ({d})", flush=True)

    # One serial retry of every skipped date. The eight sqlite shards behind the
    # SR3 store are shared, and contention on them surfaces as a cache MISS
    # rather than as a lock error -- the MDP shrugs and reaches for the vendor,
    # which under `cache_only()` is an exception and here a silently dropped
    # date. Measured on the Q20 build: dates that dropped in one pass priced
    # cleanly in the next with zero blocked requests. Retrying once makes the
    # panel deterministic, which is what a before/after comparison needs; dates
    # that fail twice are genuine and stay skipped.
    if retry and _depth != 1:
        if progress:
            print(f"  retrying {len(retry)} skipped dates", flush=True)
        rp, rr = build_panel(retry, cfg, futures_mdp=futures_mdp,
                             swaps_mdp=swaps_mdp, progress=False, _depth=1)
        if len(rp):
            panel_parts.append(rp)
        if len(rr):
            rate_rows.extend(rr.reset_index().to_dict("records"))

    panel = (pd.concat(panel_parts, ignore_index=True) if panel_parts
             else pd.DataFrame(columns=["date", "rank", "pack"]))
    rates = (pd.DataFrame(rate_rows).set_index("date").sort_index() if rate_rows
             else pd.DataFrame())
    return panel, rates


#: The Barchart STIR diskcache, 8 shards of sqlite. Keys are
#: ``f"{iso_timestamp}-{ticker}-{source}"`` with EOD rows stamped 17:00 New York.
_STIR_CACHE_KEY = re.compile(
    r"^(?P<d>\d{4}-\d{2}-\d{2})T(?P<t>\d{2}:\d{2}:\d{2})(?P<tz>[+\-]\d{2}:\d{2})?"
    r"-(?P<sym>SR3[FGHJKMNQUVXZ]\d{2})-(?P<src>[A-Z0-9_\-]+)$")


def ny_utc_offset(as_of: datetime.date, hour: int = 17) -> str:
    """``"-04:00"`` or ``"-05:00"`` -- New York's UTC offset at *hour* on *as_of*.

    The EOD request alias ``STIRFutureMDP`` writes and later reads is stamped in
    New York local time, so its offset flips with daylight saving. Any scan that
    ignores the offset is counting keys the fetcher will not find.
    """
    try:
        from zoneinfo import ZoneInfo                          # noqa: PLC0415

        off = datetime.datetime(as_of.year, as_of.month, as_of.day, hour,
                                tzinfo=ZoneInfo("America/New_York")).utcoffset()
    except Exception:                                          # noqa: BLE001
        return ""
    if off is None:
        return ""
    total = int(off.total_seconds())
    sign = "-" if total < 0 else "+"
    total = abs(total)
    return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def _tz_readable(day: str, tz: Optional[str], *, session_hour: int = 17) -> bool:
    """Is a key with this UTC offset one the EOD fetcher will actually resolve?

    **This is a measurement bug that was inflating the universe, found while
    rebuilding on 2026-08-19.** The store also carries 17:00 keys stamped
    ``+00:00`` (1,061 of them, concentrated in 2024-2026) and ``-06:00`` (902, in
    2022-2023), written by other jobs. They match the key regex, so a scan that
    accepts any offset counts them -- but ``STIRFutureMDP.get_data`` asks for the
    New-York-stamped alias and misses, then goes to the vendor.

    Measured consequence before this filter: **51 dates** whose scanned depth
    exceeded the depth actually resolvable, all but one of them in 2025-2026 --
    including 2026-07-09 and 2026-07-10, which scanned at depth **12** and
    resolve at **0**. Those dates entered the rebuilt universe, failed inside
    ``cache_only()``, and accounted for 906 blocked requests.

    ``None`` (no offset in the key) is accepted: those are pre-normalisation keys
    and the fetcher's candidate list includes the bare form.
    """
    if not tz:
        return True
    want = ny_utc_offset(datetime.date.fromisoformat(day), hour=session_hour)
    return (not want) or tz == want


def local_strip_depths(cfg: Strat2Config, *, cache_root: Optional[str] = None,
                       eod_only: bool = True) -> Dict[datetime.date, int]:
    """``date -> length of the CONTIGUOUS front SR3 strip already on this machine``.

    The permissive universe, and the one panel building should use. It answers
    *how deep is this date* rather than *is this date complete*, which is the
    only form of the question a per-rank screen can act on:
    ``max_rank_available = depth - 3``.

    Contiguity rather than mere presence, for the same reason
    :func:`strat2_q20.strip_depth_by_date` requires it -- a pack is four
    CONSECUTIVE contracts, so "11 of the first 13 present" overstates what is
    quotable. Measured on this store the distinction never binds (0 dates in
    every year at every depth have a hole before their nominal depth), but it is
    the correct measure and costs nothing.

    Reads the diskcache's sqlite shards directly (read-only) rather than probing
    the MDP, because probing IS the expensive thing being avoided.
    """
    have = _cached_symbols_by_date(cfg, cache_root=cache_root, eod_only=eod_only)
    out: Dict[datetime.date, int] = {}
    for d in sorted(have):
        dd = datetime.date.fromisoformat(d)
        if not (cfg.start <= dd <= cfg.end):
            continue
        seq = quarterly_imm_sequence(dd, cfg.n_contracts)
        depth = 0
        for y, m in seq:
            if futures_symbol(y, m, cfg.futures_root) in have[d]:
                depth += 1
            else:
                break
        out[dd] = depth
    return dict(sorted(out.items()))


def local_cached_dates(cfg: Strat2Config, *, cache_root: Optional[str] = None,
                       eod_only: bool = True,
                       min_contracts: Optional[int] = None) -> List[datetime.date]:
    """Dates whose SR3 strip is already on this machine, to a chosen depth.

    Building the panel over ``pd.bdate_range(start, end)`` would be wrong here,
    not merely slow: the SR3 store is demand-driven, a miss goes to the network,
    and a cold contract costs about a minute. Enumerating what is local first
    turns a multi-hour job that mostly fails into a three-minute one that does
    not touch the network at all -- and, just as important, makes the effective
    backtest window an observable rather than an assumption.

    ``min_contracts`` chooses the rule:

    ``None`` (default)
        **Strict** -- the FULL ``cfg.n_contracts`` strip must be present. Kept
        unchanged as the default because callers exist that genuinely want "every
        requested pack is quotable on every returned date", and because a shipped
        artifact must stay reproducible.
    an int
        **Permissive** -- the contiguous front strip must reach this many
        contracts. ``4`` is one pack window.

    The strict rule was the near-pack half of the sparse-series defect. It is
    all-or-nothing over the whole strip (``all(s in have[d] for s in names)``),
    so a date whose deferred end was cold was dropped for the front packs too.
    Prefer :func:`local_strip_depths` for new code -- it returns the depth rather
    than a yes/no, which is what lets a caller keep a date *and* know exactly how
    much of it is real.
    """
    have = _cached_symbols_by_date(cfg, cache_root=cache_root, eod_only=eod_only)
    if min_contracts is not None:
        depths = local_strip_depths(cfg, cache_root=cache_root, eod_only=eod_only)
        return [d for d, n in depths.items() if n >= int(min_contracts)]

    out: List[datetime.date] = []
    for d in sorted(have):
        dd = datetime.date.fromisoformat(d)
        if not (cfg.start <= dd <= cfg.end):
            continue
        seq = quarterly_imm_sequence(dd, cfg.n_contracts)
        names = [futures_symbol(y, m, cfg.futures_root) for y, m in seq]
        if all(s in have[d] for s in names):
            out.append(dd)
    return out


def _cached_symbols_by_date(cfg: Strat2Config, *, cache_root: Optional[str] = None,
                            eod_only: bool = True) -> Dict[str, set]:
    """``"YYYY-MM-DD" -> {SR3 tickers cached at cfg.futures_source's EOD hour}``.

    One read-only sweep of the eight sqlite shards, shared by the strict and
    permissive universes so they can never disagree about what is on disk.

    The hour is derived from the source rather than hardcoded: a settle is keyed
    15:00 and a Globex close 17:00, and a scanner still grepping ``17:00:00`` after
    a caller moved to the settle source reports depth 0 on every date -- which
    reads as "nothing is cached" and sends an idempotent warm back to the network
    for history it already holds.
    """
    from MDP.STIRFutures.STIRFutureMDP import eod_hour_for_source
    import glob
    import sqlite3

    if cache_root is None:
        try:
            from Caching.DiskCacheMixin import DiskCacheMixin  # noqa: PLC0415

            cache_root = str(DiskCacheMixin.default_cache_path("STIRFuturePricer_Cache"))
        except Exception:                                     # noqa: BLE001
            cache_root = os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "ARBS", "Cache", "diskcache",
                "dump", "STIRFuturePricer_Cache")

    eod_stamp = f"{eod_hour_for_source(cfg.futures_source):02d}:00:00"

    have: Dict[str, set] = {}
    for db in sorted(glob.glob(os.path.join(cache_root, "*", "cache.db"))):
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for (key,) in con.execute("SELECT key FROM Cache"):
                if isinstance(key, bytes):
                    key = key.decode("utf-8", "ignore")
                m = _STIR_CACHE_KEY.match(key)
                if not m:
                    continue
                if eod_only and (m.group("t") != eod_stamp
                                 or m.group("src") != cfg.futures_source
                                 or not _tz_readable(m.group("d"), m.group("tz"))):
                    continue
                have.setdefault(m.group("d"), set()).add(m.group("sym"))
        finally:
            con.close()
    return have


def _runs_of(days: pd.DatetimeIndex, max_gap_days: int) -> List[Tuple[int, int]]:
    """``[(lo, hi), ...]`` index slices of *days* with no internal gap > the max."""
    gap = pd.Series(days).diff().dt.days.fillna(0)
    breaks = [0] + list(np.where(gap > max_gap_days)[0]) + [len(days)]
    return [(breaks[i], breaks[i + 1]) for i in range(len(breaks) - 1)]


def coverage_by_run(panel: pd.DataFrame, *, max_gap_days: int = 15) -> pd.DataFrame:
    """Every contiguous run in *panel*, so trimming can be argued rather than assumed.

    :func:`trim_to_contiguous_run` throws data away. That is sometimes right, but
    it must never be the only view a reader gets -- the shipped near-pack panel
    was truncated at **2024-05-08** and nothing printed said so. This returns the
    runs with their spans and row counts; report it beside any trimmed result.
    """
    days = pd.DatetimeIndex(sorted(panel["date"].unique()))
    if not len(days):
        return pd.DataFrame(columns=["start", "end", "n_days", "span_days", "n_rows"])
    rows = []
    for lo, hi in _runs_of(days, max_gap_days):
        keep = days[lo:hi]
        rows.append({
            "start": keep[0].date(), "end": keep[-1].date(), "n_days": len(keep),
            "span_days": int((keep[-1] - keep[0]).days),
            "n_rows": int(panel["date"].isin(keep).sum()),
        })
    return pd.DataFrame(rows).sort_values("start").reset_index(drop=True)


def trim_to_contiguous_run(panel: pd.DataFrame, rates: pd.DataFrame,
                           *, max_gap_days: int = 15,
                           keep: str = "longest",
                           min_days: int = 0) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Keep one run of dates with no gap longer than *max_gap_days*, or keep all.

    The Barchart store is demand-driven, so a panel built over "every date whose
    strip is cached" comes back with the main 2019-2023 block plus a handful of
    isolated later dates that some other piece of work happened to warm. Those
    strays are poison for this strategy specifically: a rolling 63-day realized
    vol and a 252-day z-score computed across a 502-day hole are not statistics,
    and a backtest grid spanning the hole marks a position over a year of
    unobserved market.

    Dropping them is a data-availability decision, not a filter on the signal --
    no date is removed because of what its CA says.

    **What that argument does not license is `max(runs, key=length)`.** Measured
    2026-08-19 at the three shipped call sites, the longest-run rule:

    * truncated the near-pack panel at **2024-05-08** -- 1,084 dates to 1,081,
      and the three it removed are precisely the ones after the complaint's
      "~May-2024";
    * cut the Q20 deep band to 743 dates ending 2023-02-01; and
    * cut the Q20 **near** band from 518 dates to **301**, discarding every date
      in 2023, 2024 and 2025 because the longest gap-free block happened to be a
      2021 one. There it is the single largest killer in the whole pipeline,
      bigger than the depth gate.

    So the choice is now explicit, and the caller must make it:

    ``"longest"``  legacy. Longest run wins. Default, so shipped artifacts
                   reproduce; **not** what a rebuilt panel should use.
    ``"latest"``   the run ending on the most recent date. What you want when the
                   question is "what does the series look like now".
    ``"none"``     no trimming. Requires the caller to have gated its rolling
                   windows on calendar span (:attr:`Strat2Config.window_span_tolerance`),
                   or the statistics silently bridge the holes instead.

    Report :func:`coverage_by_run` alongside whichever is used.

    **``min_days`` is not optional bookkeeping -- it is what stops this
    function returning a window that cannot possibly produce a signal.**
    ``"latest"`` means ``runs[-1]``, and ``runs[-1]`` is whatever the store
    happened to warm last. Measured 2026-08-20 on the rebuilt Q20 panel, the
    last run of the deep band (ranks 8-14) is **12 dates**, 2026-07-31..
    2026-08-18, and of the near band **9 dates** -- trailing islands cut off
    from 2026-07-01 by an 18-day hole. Against
    :attr:`Strat2Config.min_history_for_z1y` = 252 every ``vs_model_z1y`` on
    such a window is NaN, so :func:`plan_epochs` skips every rebalance mark as
    warm-up, returns **zero** epochs, and :func:`run_backtest` marks a flat
    book over the 12 days. Nothing raises until :func:`assert_ran`, ~600 lines
    later, reports ``equity is identically zero`` -- which reads as "the
    strategy made no money", not "you selected a fortnight".

    So a run shorter than *min_days* is **not a candidate**, and when no run
    clears the floor this raises with the coverage table rather than handing
    back a statistically inert slice. ``min_days=0`` (the default) is the
    legacy behaviour, unchanged, so existing call sites and shipped artifacts
    reproduce; every caller whose signal has a warm-up should pass that
    warm-up. The floor is a **viability bound, not a sufficiency guarantee** --
    a run of exactly ``min_history_for_z1y`` days has one usable day and may
    still plan no epochs. The raise above and :func:`assert_ran` below cover
    the residual; what is no longer possible is failing *silently*.
    """
    if keep not in ("longest", "latest", "none"):
        raise ValueError(f"keep must be 'longest' | 'latest' | 'none', got {keep!r}")
    min_days = int(min_days)
    if min_days < 0:
        raise ValueError(f"min_days must be >= 0, got {min_days}")
    if keep == "none":
        return panel, rates
    days = pd.DatetimeIndex(sorted(panel["date"].unique()))

    def _too_short() -> ValueError:
        return ValueError(
            f"no contiguous run reaches min_days={min_days} "
            f"(max_gap_days={max_gap_days}); the panel offers only:\n"
            f"{coverage_by_run(panel, max_gap_days=max_gap_days).to_string()}\n"
            "Widen the panel, lower the floor deliberately, or use keep='none' "
            "with Strat2Config.window_span_tolerance set.")

    if len(days) < 2:
        if len(days) < min_days:
            raise _too_short()
        return panel, rates
    usable = [r for r in _runs_of(days, max_gap_days) if (r[1] - r[0]) >= min_days]
    if not usable:
        raise _too_short()
    lo, hi = (max(usable, key=lambda r: r[1] - r[0]) if keep == "longest" else usable[-1])
    keep_days = days[lo:hi]
    return (panel[panel["date"].isin(keep_days)].copy(),
            rates.loc[rates.index.isin(keep_days)].copy() if len(rates) else rates)


def panel_diagnostics(panel: pd.DataFrame, cfg: Strat2Config) -> pd.DataFrame:
    """Per-year data-quality read on the CA panel.

    SR3 did not become the liquid front-end contract overnight -- it listed in
    May 2018 and volume migrated off Eurodollars through 2021-2022 -- and the
    screen inherits that. The columns here are what makes the difference
    visible: ``ca_sd`` is the cross-sectional dispersion of the CA level and
    ``dca_sd`` the standard deviation of its DAILY change. A CA that moves
    several basis points a day at a 2-3 year point is not convexity repricing;
    it is a stale futures print marked against a live swap curve.
    """
    ca = _label_series(panel, "ca_bp")
    d = ca.diff()
    out = []
    for y, g in ca.groupby(ca.index.year):
        dg = d.loc[g.index]
        out.append({
            "year": int(y),
            "days": int(len(g)),
            "ca_median": float(np.nanmedian(g.to_numpy())),
            "ca_sd": float(np.nanstd(g.to_numpy())),
            "abs_ca_p99": float(np.nanpercentile(np.abs(g.to_numpy()), 99)),
            "dca_sd_bp": float(np.nanstd(dg.to_numpy())),
            "abs_dca_p99_bp": float(np.nanpercentile(np.abs(dg.to_numpy()), 99)),
        })
    return pd.DataFrame(out).set_index("year")


def _label_series(panel: pd.DataFrame, col: str) -> pd.DataFrame:
    """Long panel -> wide ``date x pack`` frame of one column."""
    return panel.pivot_table(index="date", columns="pack", values=col, aggfunc="last").sort_index()


def window_span_ok(index: pd.DatetimeIndex, window: int,
                   tolerance: float) -> Optional[pd.Series]:
    """Which rows may carry a ``window``-row rolling statistic, by CALENDAR span.

    ``rolling(w)`` counts rows. On a panel with holes that is not a time window
    at all, and nothing in pandas will say so: a "1Y" z-score computed from 252
    rows that happen to span 1,289 calendar days looks exactly like a real one.

    Returns a boolean Series aligned to *index* -- ``True`` where the trailing
    ``window`` rows span at most ``window / 252 * 365.25 * tolerance`` days -- or
    ``None`` when ``tolerance <= 0``, meaning the guard is off. See
    :attr:`Strat2Config.window_span_tolerance`.
    """
    if tolerance is None or tolerance <= 0:
        return None
    idx = pd.DatetimeIndex(index)
    allowed = float(window) / 252.0 * 365.25 * float(tolerance)
    start = pd.Series(idx, index=idx).shift(window - 1)
    span = (pd.Series(idx, index=idx) - start).dt.days
    return span.notna() & (span <= allowed)


def _apply_span_mask(x: pd.DataFrame, ok: Optional[pd.Series]) -> pd.DataFrame:
    """NaN out every row of *x* whose rolling window bridged a hole.

    The mask is per DATE and applies to every pack column, so it is broadcast
    across the columns rather than passed as an (n, 1) array -- ``DataFrame.where``
    requires a conditional of the same shape and will not broadcast for you.
    """
    if ok is None:
        return x
    m = ok.reindex(x.index).fillna(False).to_numpy()
    return x.where(np.repeat(m[:, None], x.shape[1], axis=1))


def panel_timeseries(panel: pd.DataFrame, cfg: Strat2Config) -> Dict[str, pd.DataFrame]:
    """The label-keyed time series every metric is derived from.

    ``ca`` and ``pack_rate`` wide frames plus the derived ``rv`` (3m realized
    vol of the pack rate, bp/yr normal), ``ca_z3m``/``ca_z1y``, and the 1-week
    change. All of them are constant-contract because the columns are labels.

    Every rolling statistic is additionally gated on the CALENDAR span of its
    window when :attr:`Strat2Config.window_span_tolerance` is set -- see
    :func:`window_span_ok`. Off by default; on in every rebuilt panel, because
    restoring coverage restores the gaps these windows would otherwise bridge in
    silence.
    """
    ca = _label_series(panel, "ca_bp")
    pr = _label_series(panel, "pack_rate")
    tol = float(getattr(cfg, "window_span_tolerance", 0.0) or 0.0)

    d = pr.diff() * 100.0                                     # bp/day
    rv = (d.rolling(cfg.realized_window_days, min_periods=cfg.realized_window_days)
          .std(ddof=1) * math.sqrt(cfg.realized_annualisation))

    def _z(x: pd.DataFrame, w: int, min_p: int) -> pd.DataFrame:
        mu = x.rolling(w, min_periods=min_p).mean()
        sd = x.rolling(w, min_periods=min_p).std(ddof=1)
        return _apply_span_mask((x - mu) / sd.replace(0.0, np.nan),
                                window_span_ok(x.index, w, tol))

    return {
        "ca": ca,
        "pack_rate": pr,
        "rv": _apply_span_mask(
            rv, window_span_ok(rv.index, cfg.realized_window_days, tol)),
        "ca_z3m": _z(ca, cfg.z_window_3m, cfg.z_window_3m),
        "ca_z1y": _z(ca, cfg.z_window_1y, cfg.min_history_for_z1y),
        "ca_chg_1w": ca.diff(cfg.week_days),
    }


def model_timeseries(panel: pd.DataFrame, cfg: Strat2Config,
                     external_sigma: Optional[pd.DataFrame] = None) -> Dict[str, pd.DataFrame]:
    """Per-date model fit across the RANKED packs -> wide ``vs_model`` series.

    The fit is run on the ranked cross-section only (``rank_start`` ..
    ``rank_start + n_packs - 1``): those are the packs the ranking compares, and
    including the near-dated windows -- whose CA is a fraction of a basis point
    and whose relative noise is therefore enormous -- would let them dominate an
    unweighted least squares.
    """
    lo, hi = cfg.rank_start, cfg.rank_start + cfg.n_packs - 1
    sub = panel[(panel["rank"] >= lo) & (panel["rank"] <= hi)]
    parts = []
    for d, day in sub.groupby("date", sort=True):
        ext = None
        if external_sigma is not None and d in external_sigma.index:
            ext = external_sigma.loc[d].to_dict()
        parts.append(_sigma_for_day(day, cfg, external=ext))
    fit = pd.concat(parts, ignore_index=True) if parts else sub.copy()
    fit["vs_model_bp"] = fit["ca_bp"] - fit["ca_model_bp"]

    vs = _label_series(fit, "vs_model_bp")
    tol = float(getattr(cfg, "window_span_tolerance", 0.0) or 0.0)

    def _z(x: pd.DataFrame, w: int, min_p: int) -> pd.DataFrame:
        mu = x.rolling(w, min_periods=min_p).mean()
        sd = x.rolling(w, min_periods=min_p).std(ddof=1)
        return _apply_span_mask((x - mu) / sd.replace(0.0, np.nan),
                                window_span_ok(x.index, w, tol))

    return {
        "fit": fit,
        "vs_model": vs,
        "sigma_model": _label_series(fit, "sigma_model_bp"),
        "ca_model": _label_series(fit, "ca_model_bp"),
        "vs_model_z3m": _z(vs, cfg.z_window_3m, cfg.z_window_3m),
        "vs_model_z1y": _z(vs, cfg.z_window_1y, cfg.min_history_for_z1y),
    }


# ===========================================================================
# The screen
# ===========================================================================
def daily_screen(
    as_of: datetime.date,
    panel: pd.DataFrame,
    cfg: Strat2Config,
    *,
    ts: Optional[Dict[str, pd.DataFrame]] = None,
    model: Optional[Dict[str, pd.DataFrame]] = None,
) -> pd.DataFrame:
    """Citi's 13-column SOFR table for one date.

    Columns, in the published order::

        CvxAdj | 1WkChg | 3m ZS | 1Y ZS | Model(bp) | Vs Model(bp) | 3m ZS |
        1Y ZS | 3m Roll | Implied Vol | Realized Vol | Implied/Realized |
        Cap vol Impl/Rlzd

    ``Implied/Realized`` is ROUNDED to 1dp and ``Cap vol Impl/Rlzd`` is
    TRUNCATED to 1dp -- reproduced literally, because that asymmetry is what
    ties out 26/26 rows across Citi's ED and SOFR tables.
    """
    ts = ts if ts is not None else panel_timeseries(panel, cfg)
    model = model if model is not None else model_timeseries(panel, cfg)
    d = pd.Timestamp(as_of)
    day = panel[panel["date"] == d]
    if day.empty:
        return pd.DataFrame()

    lo, hi = cfg.rank_start, cfg.rank_start + cfg.n_packs - 1
    ranked = day[(day["rank"] >= lo) & (day["rank"] <= hi)].sort_values("rank")
    by_rank = day.set_index("rank")

    def _at(frame: Optional[pd.DataFrame], pack: str) -> float:
        if frame is None or d not in frame.index or pack not in frame.columns:
            return float("nan")
        return float(frame.at[d, pack])

    rows = []
    for _, r in ranked.iterrows():
        pack = r["pack"]
        ca = float(r["ca_bp"])
        w = float(r["time_weight"])
        # sqrt(M) as a single pseudo-T1 reproduces the pack time weight exactly
        iv = (implied_vol_from_ca_bp(ca, [math.sqrt(w)], convention=cfg.holee_convention)
              if (ca >= cfg.ca_floor_bp and w > 0) else float("nan"))
        rv = _at(ts.get("rv"), pack)
        sig_m = _at(model.get("sigma_model"), pack)
        nearer = by_rank.loc[r["rank"] - 1, "ca_bp"] if (r["rank"] - 1) in by_rank.index else np.nan
        ir = iv / rv if (np.isfinite(iv) and np.isfinite(rv) and rv > 0) else float("nan")
        capr = sig_m / rv if (np.isfinite(sig_m) and np.isfinite(rv) and rv > 0) else float("nan")
        rows.append({
            "rank": int(r["rank"]),
            "pack": pack,
            "colour": r["colour"],
            "swap_start": r["swap_start"],
            "swap_end": r["swap_end"],
            "ca_bp": ca,
            "ca_chg_1w_bp": _at(ts.get("ca_chg_1w"), pack),
            "ca_z3m": _at(ts.get("ca_z3m"), pack),
            "ca_z1y": _at(ts.get("ca_z1y"), pack),
            "ca_model_bp": _at(model.get("ca_model"), pack),
            "vs_model_bp": _at(model.get("vs_model"), pack),
            "vs_model_z3m": _at(model.get("vs_model_z3m"), pack),
            "vs_model_z1y": _at(model.get("vs_model_z1y"), pack),
            "roll_3m_bp": ca - float(nearer) if np.isfinite(nearer) else float("nan"),
            "implied_vol_bp": iv,
            "realized_vol_bp": rv,
            "sigma_model_bp": sig_m,
            "implied_over_realized": round(ir, 1) if np.isfinite(ir) else float("nan"),
            "capvol_over_realized": math.trunc(capr * 10) / 10 if np.isfinite(capr) else float("nan"),
            "implied_over_realized_raw": ir,
        })
    return pd.DataFrame(rows).set_index("pack", drop=False)


def rank_flags(screen: pd.DataFrame, cfg: Strat2Config) -> pd.DataFrame:
    """Per-metric top-``n`` flags. *"we mark three best short convexity trades."*

    A pack is a more attractive SHORT-convexity candidate the HIGHER each
    metric is, uniformly -- so the rule is one ``nlargest`` per metric over the
    finite values only. A metric with fewer than ``top_n_per_metric`` finite
    values still votes, with whatever it has; a metric with none does not.
    """
    flags = pd.DataFrame(False, index=screen.index,
                         columns=list(cfg.rank_metrics))
    for m in cfg.rank_metrics:
        if m not in screen.columns:
            continue
        s = screen[m].dropna()
        if s.empty:
            continue
        for p in s.nlargest(min(cfg.top_n_per_metric, len(s))).index:
            flags.at[p, m] = True
    flags["n_flags"] = flags.sum(axis=1)
    return flags


def select_pack(screen: pd.DataFrame, cfg: Strat2Config) -> Tuple[Optional[str], pd.DataFrame]:
    """*"select the pack flagged by the MOST metrics."*

    Ties are broken by the pack's mean cross-sectional percentile rank across
    the same metrics, which is deterministic and uses the same information the
    flags do -- rather than by index order, which would silently prefer the
    front of the strip.
    """
    if screen.empty:
        return None, pd.DataFrame()
    flags = rank_flags(screen, cfg)
    pct = pd.DataFrame(index=screen.index)
    for m in cfg.rank_metrics:
        if m in screen.columns:
            pct[m] = screen[m].rank(pct=True)
    flags["mean_pct"] = pct.mean(axis=1)
    ordered = flags.sort_values(["n_flags", "mean_pct"], ascending=False)
    best = ordered.index[0]
    if int(ordered.loc[best, "n_flags"]) < cfg.min_metrics_flagged:
        return None, flags
    return str(best), flags


# ===========================================================================
# The 2s5s10s hedge
# ===========================================================================
@dataclass(frozen=True)
class HedgeFit:
    """One trailing regression of a pack's CA on the 2y/5y/10y par rates."""

    alpha: float
    b2: float
    b5: float
    b10: float
    beta: float          # = b5, bp of CA per PERCENT of fly
    w2: float            # DV01 weight on the 2y wing, belly normalised to 1
    w10: float
    r2: float            # regression R^2
    n_obs: int
    ok: bool
    reason: str = ""

    def fitted_fly_bp(self, r2y: float, r5y: float, r10y: float) -> float:
        """``alpha + beta * (-w2*r2 + r5 - w10*r10)``, the chart annotation."""
        return self.alpha + self.beta * (-self.w2 * r2y + r5y - self.w10 * r10y)


def hedge_regression(ca: pd.Series, rates: pd.DataFrame, cfg: Strat2Config) -> HedgeFit:
    """``CA(bp) ~ a + b2*r2y + b5*r5y + b10*r10y`` on the trailing window.

    Citi's chart annotation is ``CA_fitted = alpha + beta * fly`` with
    ``fly = -w2*r2 + r5 - w10*r10`` in percent, so ``beta = b5``,
    ``w2 = -b2/beta`` and ``w10 = -b10/beta``. On 13-Jan-2017 that was
    ``10.2 + 21.4*(-0.73*2y + 5y - 0.47*10y)``; on 09-Feb-2017,
    ``9.7 + 20.6*(-0.705*2y + 5y - 0.465*10y)``. **Both are re-estimated here,
    never hardcoded.**
    """
    t2, t5, t10 = cfg.hedge_tenors
    j = pd.concat([ca.rename("ca"), rates[[t2, t5, t10]]], axis=1).dropna()
    j = j.tail(cfg.hedge_regression_days)
    n = len(j)
    if n < max(30, cfg.hedge_regression_days // 4):
        return HedgeFit(*(np.nan,) * 8, n_obs=n, ok=False, reason=f"only {n} obs")
    x = np.column_stack([np.ones(n), j[t2], j[t5], j[t10]])
    y = j["ca"].to_numpy(float)
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    a, b2, b5, b10 = (float(c) for c in coef)
    resid = y - x @ coef
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else float("nan")
    if abs(b5) < cfg.hedge_min_abs_beta:
        return HedgeFit(a, b2, b5, b10, b5, np.nan, np.nan, r2, n, False,
                        f"|beta|={abs(b5):.2f} < {cfg.hedge_min_abs_beta}")
    w2, w10 = -b2 / b5, -b10 / b5
    ok, why = True, ""
    if cfg.hedge_require_positive_wings and (w2 <= 0 or w10 <= 0):
        ok, why = False, f"wing weight not expressible as a fly (w2={w2:.3f}, w10={w10:.3f})"
    return HedgeFit(a, b2, b5, b10, b5, w2, w10, r2, n, ok, why)


def hedge_sizing(fit: HedgeFit, ca_dv01: float) -> Dict[str, float]:
    """*"belly_DV01 = CA_DV01 * beta / 100; wings = w2*belly, w10*belly."*

    Verified against both published trades: $100k CA DV01 at beta 21.4 needs a
    $21,400/bp belly and Citi published -$44.4mn of 5y, which is $21,312/bp at
    the era's $480/mn -- ratio 0.996. $200k at beta 20.6 -> $41,200 vs $41,088,
    ratio 0.997. The fly is deliberately NOT DV01-matched to the CA leg; the
    belly is only ~21% of it, because it is a BETA hedge for the vol exposure.
    """
    belly = float(ca_dv01) * float(fit.beta) / 100.0
    return {"belly_dv01": belly,
            "wing_2y_dv01": float(fit.w2) * belly,
            "wing_10y_dv01": float(fit.w10) * belly}


# ===========================================================================
# The trade
# ===========================================================================
@dataclass(frozen=True)
class TradeSpec:
    """Everything needed to instantiate one epoch of the strategy."""

    entry: datetime.date
    exit: datetime.date
    pack: str
    rank: int
    symbols: Tuple[str, ...]
    swap_start: datetime.date
    swap_end: datetime.date
    contracts_per_leg: int
    ca_dv01: float
    n_flags: int
    ca_entry_bp: float
    hedge: Optional[HedgeFit] = None
    hedge_dv01: Optional[Dict[str, float]] = None
    tag: str = ""


def build_trade_queries(spec: TradeSpec, cfg: Strat2Config, *, hedged: bool) -> List[Any]:
    """The queries for one epoch: 4 futures legs + the matched swap + the fly.

    **Short convexity** = buy the pack, pay the matched swap::

        futures : contracts = +n on each of the four legs (long the future =
                  short the rate). Four SEPARATE OUTRIGHT queries, not a pack
                  alias -- the STIR handler marks a multi-leg package with the
                  UNWEIGHTED PV01 sum against the risk-WEIGHTED price sum, which
                  quadruples a 4-leg pack's P&L. Verified numerically.
        swap    : bpv = +CA_DV01 (payer), explicit effective/maturity dates.
        fly     : bpv = +belly_DV01 (pay the belly), risk_weights [w2, 1, w10].
                  ``_build_fly`` MUTATES the risk_weights list in place, so a
                  fresh list is constructed here for every query.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
    from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
    from Query.STIRFutures.STIRFutureValue import STIRFutureValue

    tag = spec.tag or f"s2_{spec.pack}_{spec.entry:%Y%m%d}"
    out: List[Any] = []
    for sym in spec.symbols:
        out.append(STIRFutureQuery(
            structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE,
            symbol=sym, structure_kwargs={"contracts": int(spec.contracts_per_leg)},
            tags=(tag,)))
    out.append(IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, curve=cfg.curve,
        effective_date=spec.swap_start, maturity_date=spec.swap_end,
        structure_kwargs={"bpv": float(spec.ca_dv01)}, tags=(tag,)))
    if hedged and spec.hedge is not None and spec.hedge.ok and spec.hedge_dv01:
        t2, t5, t10 = cfg.hedge_tenors
        out.append(IRSwapQuery(
            structure=IRSwapStructure.FLY, value=IRSwapValue.NPV, curve=cfg.curve,
            structure_kwargs={
                "front_tenor": t2, "belly_tenor": t5, "back_tenor": t10,
                # fresh list: _build_fly rewrites it in place
                "risk_weights": [float(spec.hedge.w2), 1.0, float(spec.hedge.w10)],
                "bpv": float(spec.hedge_dv01["belly_dv01"])},
            tags=(tag,)))
    return out


def plan_epochs(
    panel: pd.DataFrame,
    rates: pd.DataFrame,
    cfg: Strat2Config,
    *,
    ts: Optional[Dict[str, pd.DataFrame]] = None,
    model: Optional[Dict[str, pd.DataFrame]] = None,
    verbose: bool = True,
) -> List[TradeSpec]:
    """Walk the rebalance calendar and produce the sequence of held epochs.

    The book is re-struck only when the screen's selected pack CHANGES or the
    hold exceeds ``max_hold_months``. That is what Citi did -- it rolled Blues
    (9-Feb -> 6-Jun 2017) into Greens (6-Jun -> 8-Aug 2017) rather than closing
    the theme -- and it keeps the "matched-maturity" swap actually matched.
    """
    ts = ts if ts is not None else panel_timeseries(panel, cfg)
    model = model if model is not None else model_timeseries(panel, cfg)
    days = pd.DatetimeIndex(sorted(panel["date"].unique()))
    if len(days) == 0:
        return []
    cand = pd.DatetimeIndex(sorted(set(
        pd.date_range(days[0], days[-1], freq=cfg.rebalance_freq))))
    # snap each rebalance date to the next available panel day
    marks: List[pd.Timestamp] = []
    for c in cand:
        nxt = days[days >= c]
        if len(nxt):
            m = nxt[0]
            if not marks or m != marks[-1]:
                marks.append(m)

    specs: List[TradeSpec] = []
    cur: Optional[TradeSpec] = None
    cur_entry: Optional[pd.Timestamp] = None
    for m in marks:
        screen = daily_screen(m.date(), panel, cfg, ts=ts, model=model)
        if screen.empty:
            continue
        # a screen with no usable 1y z-scores is a warm-up day, not a signal
        if not np.isfinite(screen["vs_model_z1y"]).any():
            continue
        pick, flags = select_pack(screen, cfg)
        stale = (cur_entry is not None
                 and m >= cur_entry + pd.DateOffset(months=cfg.max_hold_months))
        if cur is not None and pick == cur.pack and not stale:
            continue
        if cur is not None:
            specs.append(replace(cur, exit=m.date()))
            cur, cur_entry = None, None
        if pick is None:
            continue
        row = screen.loc[pick]
        ca_hist = ts["ca"][pick] if pick in ts["ca"].columns else pd.Series(dtype=float)
        fit = hedge_regression(ca_hist.loc[:m], rates.loc[:m], cfg)
        sizing = hedge_sizing(fit, cfg.ca_dv01) if fit.ok else None
        day = panel[(panel["date"] == m) & (panel["pack"] == pick)].iloc[0]
        specs_symbols = tuple(futures_symbol(y, mo, cfg.futures_root)
                              for y, mo in _contracts_for(pick, m.date(), cfg))
        cur = TradeSpec(
            entry=m.date(), exit=days[-1].date(), pack=pick, rank=int(row["rank"]),
            symbols=specs_symbols, swap_start=day["swap_start"], swap_end=day["swap_end"],
            contracts_per_leg=int(round(cfg.ca_dv01 / (4.0 * DV01_PER_CONTRACT))),
            ca_dv01=float(cfg.ca_dv01), n_flags=int(flags.loc[pick, "n_flags"]),
            ca_entry_bp=float(row["ca_bp"]), hedge=fit, hedge_dv01=sizing,
            tag=f"s2_{pick}_{m:%Y%m%d}")
        cur_entry = m
        if verbose:
            h = (f"beta {fit.beta:.1f} w {fit.w2:.3f}/1/{fit.w10:.3f} R2 {fit.r2:.2f}"
                 if fit.ok else f"NO HEDGE ({fit.reason})")
            print(f"  {m:%Y-%m-%d} enter {pick} (rank {int(row['rank'])}, "
                  f"{int(flags.loc[pick, 'n_flags'])} flags, CA {row['ca_bp']:+.2f}bp) {h}")
    if cur is not None:
        specs.append(replace(cur, exit=days[-1].date()))
    return specs


def _contracts_for(label: str, as_of: datetime.date, cfg: Strat2Config
                   ) -> Tuple[Tuple[int, int], ...]:
    """Resolve a pack LABEL back to its four ``(year, month)`` contracts."""
    for spec in pack_windows(as_of, cfg):
        if spec.label == label:
            return spec.contracts
    raise KeyError(f"{label!r} is not a pack window on {as_of}")


# ===========================================================================
# The backtest
# ===========================================================================
def run_backtest(
    specs: Sequence[TradeSpec],
    cfg: Strat2Config,
    *,
    hedged: Optional[bool] = None,
    futures_mdp: Any = None,
    swaps_mdp: Any = None,
    trading_days: Optional[Sequence[pd.Timestamp]] = None,
    name: Optional[str] = None,
    show_progress: bool = False,
) -> Any:
    """Run the epochs through ``QueryDrivenBacktest`` with daily mark-to-market.

    ``hedged`` defaults to ``cfg.hedge_enabled`` and overrides it when passed,
    which is what makes a hedged-vs-unhedged comparison one config and two
    calls rather than two configs whose other 30 knobs have to be kept in sync.

    Two market-data providers are wired by product string --
    ``{"STIRFUTURE": STIRFutureMDP, "IRS": IRSwapsMDP}`` -- because the package
    spans both. ``QueryDrivenBacktest.run()`` SWALLOWS exceptions and prints
    them, so a silently-failing backtest is indistinguishable from a flat equity
    curve; the caller must assert on ``mtm_history``. :func:`assert_ran` does.
    """
    hedged = bool(cfg.hedge_enabled) if hedged is None else bool(hedged)
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    futures_mdp = futures_mdp or STIRFutureMDP(source=cfg.futures_source)
    swaps_mdp = swaps_mdp or IRSwapsMDP(source=cfg.swap_source)

    triggers = []
    fee = float(cfg.cost_bp_per_roundtrip) * float(cfg.ca_dv01)
    for spec in specs:
        qs = build_trade_queries(spec, cfg, hedged=hedged)
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[spec.entry]),
            actions=[AddQueryAction(query=q, meta={"tags": [spec.tag]}) for q in qs]))
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[spec.exit]),
            actions=[UnwindPositionsAction(match_tag=spec.tag, fee=fee)]))

    if trading_days is None:
        lo = min(s.entry for s in specs)
        hi = max(s.exit for s in specs)
        trading_days = pd.bdate_range(lo, hi)
    grid = TimeGrid([pd.Timestamp(d) for d in trading_days])

    strat = QueryStrategy(name=name or f"strat2_{'hedged' if hedged else 'unhedged'}",
                          triggers=triggers)
    strat.mdps = {"STIRFUTURE": futures_mdp, "IRS": swaps_mdp}
    strat.default_mdp = swaps_mdp
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=swaps_mdp,
                             show_progress=show_progress)
    bt.run()
    return bt


def assert_ran(bt: Any, specs: Sequence[TradeSpec], *, hedged: bool,
               expect_days: Optional[int] = None) -> pd.Series:
    """``run()`` swallows exceptions -- so prove the book actually traded.

    A backtest that never fired a trigger has no equity-curve holes, no NaNs
    and a perfectly flat curve. Every assertion here exists because that failure
    mode is indistinguishable from "the strategy made no money".

    ``specs`` is checked FIRST and by name. An empty plan is not a trading
    result, it is a planning failure, and reporting it as ``equity is
    identically zero`` sends the reader looking for a P&L bug when the cause
    is upstream -- measured 2026-08-20, a 12-date panel window whose
    ``vs_model_z1y`` is NaN throughout, so :func:`plan_epochs` warm-up-skipped
    every rebalance mark. The window, not the book, is what to look at.
    """
    n_days = len(pd.DatetimeIndex(sorted(pd.Series(bt.mtm_history).index)))
    assert len(specs) > 0, (
        f"plan_epochs produced NO epochs over the {n_days}-day window -- nothing "
        "was ever planned, so the flat equity curve is a planning failure, not a "
        "trading result. Usual cause: the window is shorter than "
        "Strat2Config.min_history_for_z1y, so every vs_model_z1y is NaN and every "
        "rebalance mark is skipped as warm-up. Check coverage_by_run() and the "
        "min_days floor passed to trim_to_contiguous_run().")
    eq = pd.Series(bt.mtm_history)
    assert len(eq) > 0, "mtm_history is empty -- the engine swallowed an exception"
    if expect_days is not None:
        assert len(eq) == expect_days, f"expected {expect_days} marks, got {len(eq)}"
    eq.index = pd.to_datetime(eq.index)
    assert float(eq.abs().max()) > 0, "equity is identically zero -- no trigger fired"
    closed = getattr(bt.portfolio, "closed_positions_log", []) or []
    # 4 futures legs + the matched swap on every epoch; the fly is extra and is
    # skipped whenever the trailing regression is not expressible as a fly.
    want = 5 * len(specs)
    assert len(closed) >= want, (
        f"expected >= {want} closed legs for {len(specs)} epochs, got {len(closed)} "
        "-- the futures legs did not trade")
    if hedged:
        n_hedged = sum(1 for s in specs if s.hedge is not None and s.hedge.ok)
        assert len(closed) >= want + n_hedged, (
            f"{n_hedged} epochs carried a fly but only {len(closed) - want} extra legs closed")
    return eq
