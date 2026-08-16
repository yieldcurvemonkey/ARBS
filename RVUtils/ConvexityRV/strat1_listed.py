"""Strategy 1-listed -- the curve as gamma, priced against EXCHANGE-LISTED vol.

``strat1_curve_gamma`` implements JPM's question ("An option by any other name",
Younger/Sarkar/Salem, 03-Feb-2017) with the OTC swaption as the benchmark::

    "The same can also be said when the level of volatility priced into the
     curve is less than that implied by ATMF swaptions."

This module replaces that benchmark with listed vol and keeps everything else
identical -- same payoff kernel, same breakeven solve, same cohort machinery,
same sign convention. Only the right-hand side of the comparison changes.

That is a real question rather than a relabelling because listed and OTC vol are
different markets with different flows: swaption vol is set by structured-product
and mortgage-convexity hedging, listed vol by macro funds and dealer gamma. The
curve can be cheap against one and rich against the other, and the OTC/listed
basis is itself a traded thing. So this module computes BOTH signals on every
date -- ``signal_listed`` and ``signal_otc`` -- from the same curve breakeven,
and reports the basis between the two benchmarks. If the two signals agreed
everywhere the exercise would indeed be a relabelling, and the panel is built so
that fact would be visible instead of assumed either way.


Two modes, two sectors
----------------------
**SFR mode (the original, unchanged).** Strategy 1's universe is LONG-END, and
when this module was written the only listed vol available offline was **SFR
(3M SOFR futures) options**, which price the SHORT END. Comparing a 30-year
curve structure to a 3M-SOFR option would be a sector mismatch and a fake
result, so the SFR mode's universe is a set of **SFR-sector forward flatteners**
-- :data:`SFR_STRUCTURES` -- chosen to sit inside the span the SFR strip
actually prices, matched on every date to the contract whose expiry is nearest
the curve horizon. Everything about that mode is as it was;
``strat1_threeway`` depends on it and none of its behaviour changes here.

**UST long-end mode (new).** ``scripts/harvest_ust_listed_vol.py`` closed the
gap by harvesting QuikStrike CONSTANT-MATURITY ATM vol for the whole UST futures
complex, 2019-01-02..2026-08-14 -- so strategy 1's own long-end structures now
have a listed benchmark over the full curve window rather than none. That mode
lives in :func:`build_longend_listed_panel` and the ``longend_*`` reporting
functions, and it answers the question the SFR mode could not:

    Strategy 1's long-end flatteners were cheap against 1Yx30Y swaptions on
    essentially every day of 2019-2026. Was that the curve being cheap, or
    swaptions being the expensive comparison?

The two modes differ in what they can support, and the difference is not
cosmetic. The SFR panel is a full strike-by-strike smile, so it carries both the
note's signals. The UST panel is **ATM only, at 30/60/90-day constant maturity**
-- no strikes -- so the long-end mode computes the **breakeven-vol** signal and
does not pretend to an expected-payoff one.


Sector matching in the long-end mode -- by measured CTD, not by contract name
-----------------------------------------------------------------------------
:data:`listed_vol.UST_SECTOR_MAP` assigns each structure a primary, an alt and a
deliberately-wrong control root, driven by the measured remaining maturity of
each contract's cheapest-to-deliver (``listed_vol.UST_CTD_PROFILE``). The
consequence worth stating up front: the contract named "30-year bond" (US) has a
CTD with a median **15.9 years** left, so the primary benchmark for 30Y/50Y is
the **Ultra Bond (UL, CTD 25.6 years)**, not US.

TY (CTD 6.8 years) is carried on every structure as a control that SHOULD score
worse. It is there to make a specific failure visible: if a 7-year benchmark
ranks a 30s/50s structure as well as a 30-year one, the comparison is not
measuring sector. Read :func:`longend_signal_distribution` with that in mind --
on the three saturated structures the *cheap-share* cannot tell the roots apart
(it is 100% against all of them), and the sector separation is visible only in
the benchmark LEVELS and the gap distribution. That is a property of the result,
not a defect in the control, and it is called out in
:func:`longend_benchmark_separation`.


Residual mismatches in the SFR mode, not hidden:

* **Underlying tenor.** The SFR option's underlying is a 3M rate; the curve legs
  are 2-3Y swap rates. Short rates are more volatile than longer ones, so the
  listed benchmark is biased *high* relative to a perfectly matched one, which
  biases the signal towards "curve is rich". The 1Yx2Y ATMF swaption control
  (``otc_expiry``/``otc_tenor``) measures exactly this bias, because it shares
  the listed panel's sector and the curve legs' tenor.
* **Expiry.** The curve breakeven is a 1-year-horizon number; the matched listed
  expiry is within a measured 45 days of that on every usable date (median 23).
  Both sides are quoted in bp/day, which removes the horizon to first order, and
  ``listed_gap_days`` plus the listed term structure are carried on every row so
  the residual is auditable.


Structure universe -- why these and not the obvious ones
--------------------------------------------------------
The obvious short-end pairs are 1Y-tailed (1Yx1Y/2Yx1Y, 2Yx1Y/3Yx1Y). They are
excluded, for a measured reason rather than a stylistic one: carry-and-roll over
a **1-year** horizon on a **1-year** tail rolls the swap to zero length and the
engine raises ``ValueError: Schedule 'termination' must be after 'effective'``.
Verified on 2025-03-03 for 1Yx1Y/2Yx1Y -- fails at horizon ``1Y``, returns
+2.599 bp at ``6M``, +4.080 bp at ``3M``. Rather than silently shorten the
horizon for some structures and not others (which would make the bp/day
comparison inconsistent across the panel), the universe uses 2Y and 3Y tails and
keeps one horizon everywhere.


The shift grid is WIDER than strategy 1's, and that is not cosmetic
--------------------------------------------------------------------
``normal_pdf_weights`` normalises over the supplied grid, so a truncated grid is
a truncated normal: as sigma grows the weights approach uniform and the expected
payoff saturates at the grid's *mean* payoff. For long-end structures with
JPM's +/-250 bp axis that ceiling is far above any plausible carry. For short-end
structures the convexity per bp of shift is an order of magnitude smaller, and
the ceiling starts binding -- so the breakeven solve returns ``never_cheap``
where the truth is "a root exists past the edge of the grid". Measured, same
dates and structures, +/-250 vs +/-500 bp:

===========  ==========  =================  =================
date         structure   +/-250 grid        +/-500 grid
===========  ==========  =================  =================
2025-03-03   1Yx2Y/2Yx2Y  never_cheap        21.311 bp/day
2024-09-03   1Yx3Y/2Yx3Y  never_cheap        18.233 bp/day
2024-09-03   2Yx2Y/3Yx2Y  10.835 bp/day       9.430 bp/day
2025-03-03   2Yx3Y/3Yx3Y   6.392 bp/day       6.403 bp/day
===========  ==========  =================  =================

i.e. it changes a *classification* where the grid binds and moves a converged
root by well under a bp where it does not. +/-500 bp is ~5.5 sigma of the
measured 5.7 bp/day realised SFR vol over a 1-year horizon, so the remaining
truncation is negligible.


Sign convention (inherited, re-verified in the notebook)
--------------------------------------------------------
::

    OUTRIGHT bpv > 0  =  PAYER
    CURVE    bpv < 0  =  FLATTENER (pay front, receive back)  =  LONG convexity
    CURVE    bpv > 0  =  STEEPENER                            =  SHORT convexity

    signal +1 = curve is CHEAP gamma -> FLATTENER
    signal -1 = curve is RICH  gamma -> STEEPENER


Sample length -- stated up front
--------------------------------
The SFR panel is 540 daily dates (2024-07-01..2026-07-28), of which 525 carry a
horizon-matched expiry. That is ~2 years, and with 1-year holding periods it
contains roughly **one** non-overlapping observation per structure. It cannot
support a Sharpe ratio, and that mode's headline output is deliberately
:func:`signal_distribution` -- how often, and by how much, the curve is cheap
against listed vol -- with the cohort P&L reported as an illustration carrying
its own sample-size caveat.

The UST long-end panel is 1,917 daily dates (2019-01-02..2026-08-14) for US, TY
and FV; 1,662 for UL; 1,647 for TU; and only 639 for TN, which is a newer
contract. Those windows are NOT the same, and a table that compares a UL number
to a TN number without carrying ``n`` and the window is comparing two different
samples -- so :func:`longend_signal_distribution` carries both on every row.


Horizon: a 1-year breakeven against a 30-day quote
---------------------------------------------------
The curve breakeven is a **1-year**-horizon number; the UST quotes are 30, 60
and 90-day constant maturity. Both sides are annualised and divided by
``sqrt(252)``, which removes the horizon to first order but not exactly -- the
listed term structure is not flat. Measured (``listed_vol.ust_cm_term_structure``),
the 30->90 day slope in ABPV is US **+2.31%**, UL **+4.39%**, TY +1.73%, TN
+0.10%, i.e. **0.13, 0.23, 0.10 and 0.01 bp/day**. Over the same tail the OTC
term structure runs the other way (1Mx30Y median 80.80 vs 1Yx30Y 78.94, -2.3%),
so extrapolating the listed CM points out to a 1-year expiry would move the
benchmark by single-digit percent at most, and in the direction that makes the
curve look CHEAPER still. :func:`longend_term_structure_effect` reports how far
each structure's verdict actually moves across 30/60/90 rather than asserting
that it does not.
"""

from __future__ import annotations

import dataclasses
import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV import listed_vol as lv
from RVUtils.ConvexityRV.payoff import expected_payoff
from RVUtils.ConvexityRV.strat1_curve_gamma import (
    FLATTENER,
    STEEPENER,
    Strat1Config,
    breakeven_vol,
    build_backtest,
    cohort_dates,
    cohort_schedule,
    cohort_table,
    is_convex,
    signal_from_breakeven,
    signal_from_expected_payoff,
    structure_profile,
    vol_bp_per_day,
)

#: Re-exported verbatim from ``strat1_curve_gamma`` rather than reimplemented.
#: The curve side of this study must be bit-identical to strategy 1's or a
#: divergence between the two would be un-diagnosable, so the cohort machinery,
#: the breakeven solve and the engine wiring are imported, not copied.
__all__ = [
    "Strat1ListedConfig",
    "SFR_STRUCTURES",
    "LONG_END_STRUCTURES",
    "WIDE_SHIFTS_BP",
    "listed_signal_row",
    "shift_density",
    "build_listed_signal_panel",
    "signal_distribution",
    "vol_basis_frame",
    "long_end_reference_frame",
    # --- UST long-end mode
    "LONGEND_SHIFTS_BP",
    "build_longend_listed_panel",
    "longend_signal_distribution",
    "longend_vol_basis",
    "longend_term_structure_effect",
    "longend_benchmark_separation",
    "longend_curve_regression",
    # --- re-exports from strat1_curve_gamma
    "breakeven_vol",
    "structure_profile",
    "signal_from_breakeven",
    "signal_from_expected_payoff",
    "is_convex",
    "cohort_dates",
    "cohort_schedule",
    "build_backtest",
    "cohort_table",
    "FLATTENER",
    "STEEPENER",
]


#: Terminal parallel shifts, bp. Wider than strategy 1's +/-250 -- see the module
#: docstring for the measurement that forced it. Uneven by design: 25 bp steps
#: through the money where the profile curves, 100 bp in the wings where it is
#: nearly linear.
WIDE_SHIFTS_BP: Tuple[float, ...] = (
    -500.0, -400.0, -300.0, -250.0, -200.0, -150.0, -100.0, -75.0, -50.0, -25.0,
    0.0,
    25.0, 50.0, 75.0, 100.0, 150.0, 200.0, 250.0, 300.0, 400.0, 500.0,
)

#: (label, front_tenor, back_tenor). Forward notation "AYxBY" = a B-year swap
#: starting in A years; the FRONT leg is the shorter-dated one, and a flattener
#: pays it and receives the back.
#:
#: All four sit in the 1Y..6Y part of the curve, which is the span the SFR strip
#: (SFRH25..SFRH28, expiries 0.0-3.5 years forward on a 3M rate) actually prices.
#: 1Y tails are excluded -- see the module docstring. Every one of these was
#: checked to resolve, carry and price convexly on 2024-09-03, 2025-03-03 and
#: 2026-03-03.
SFR_STRUCTURES: Tuple[Tuple[str, str, str], ...] = (
    ("1Yx2Y/2Yx2Y", "1Yx2Y", "2Yx2Y"),   # tightest to the front of the strip
    ("2Yx2Y/3Yx2Y", "2Yx2Y", "3Yx2Y"),   # one year further out
    ("1Yx3Y/2Yx3Y", "1Yx3Y", "2Yx3Y"),   # longer tail, same forward span
    ("2Yx3Y/3Yx3Y", "2Yx3Y", "3Yx3Y"),
    ("1Yx2Y/3Yx2Y", "1Yx2Y", "3Yx2Y"),   # two-year forward span: more convexity
)

#: Strategy 1's own long-end universe -- and, since the constant-maturity UST
#: harvest, the universe of this module's UST mode. Every one of these now HAS a
#: listed benchmark; :data:`listed_vol.UST_SECTOR_MAP` says which.
#:
#: ``5Y/30Y`` is kept even though it is not one of the note's forward structures,
#: for a reason that only became visible once the listed comparison was run: it
#: is the ONLY one of the four whose cheap/rich verdict is not saturated at 100%,
#: so it is the only structure on which the choice of benchmark can move the
#: answer at all. Dropping it would leave a study in which every number is 1.00.
LONG_END_STRUCTURES: Tuple[Tuple[str, str, str], ...] = (
    ("30Y/50Y", "30Y", "50Y"),
    ("20Yx5Y/25Yx5Y", "20Yx5Y", "25Yx5Y"),
    ("10Yx10Y/20Yx10Y", "10Yx10Y", "20Yx10Y"),
    ("5Y/30Y", "5Y", "30Y"),
)

#: The shift grid the long-end mode uses: strategy 1's OWN +/-250 bp axis, NOT
#: :data:`WIDE_SHIFTS_BP`.
#:
#: This is load-bearing and easy to get wrong. The wide grid exists because
#: SHORT-end structures have an order of magnitude less convexity per bp and the
#: breakeven solve saturates against a truncated normal on the narrow grid. Long-
#: end structures do not have that problem -- and, more importantly, the stored
#: ``strat1_signal_panel.parquet`` this mode reuses was built on the +/-250 grid.
#: Re-deriving the curve side on a different grid would produce a second
#: breakeven number that disagrees with strategy 1's for a reason that has
#: nothing to do with the listed benchmark. :func:`longend_curve_regression`
#: exists to prove the reuse is exact, and it drives the profile through this
#: grid for that reason.
LONGEND_SHIFTS_BP: Tuple[float, ...] = (
    -250.0, -200.0, -150.0, -100.0, -50.0, -25.0,
    0.0,
    25.0, 50.0, 100.0, 150.0, 200.0, 250.0,
)


@dataclass(frozen=True)
class Strat1ListedConfig:
    """Every knob of strategy 1-listed. Nothing here is tuned on the backtest."""

    # ---------------------------------------------------------------- universe
    #: (label, front_tenor, back_tenor) triples, sector-matched to the listed
    #: panel. See :data:`SFR_STRUCTURES`.
    structures: Tuple[Tuple[str, str, str], ...] = SFR_STRUCTURES
    #: Curve every leg is built on.
    curve: str = "USD-SOFR-1D"
    #: Package risk. Both legs are struck to this |pv01|, so the package is
    #: DV01-neutral by construction and all P&L is reported in bp of this.
    package_dv01: float = 100_000.0

    # ------------------------------------------------------------------ signal
    #: Holding period AND the horizon the carry-and-roll is measured over AND the
    #: target the listed expiry is matched to. A 1-year tail cannot survive a
    #: 1-year roll (see the module docstring), which is why the universe starts
    #: at 2Y tails rather than why this is 1Y.
    horizon: str = "1Y"
    #: The same horizon as a year fraction, for the vol scaling. Separate because
    #: ``horizon`` is a rateslib tenor string.
    horizon_years: float = 1.0
    #: Terminal parallel shifts, bp. Wider than strategy 1's; see the module
    #: docstring for the saturation measurement that required it.
    shifts_bp: Tuple[float, ...] = WIDE_SHIFTS_BP
    #: "breakeven_vol" (the note's primary signal, and the only one the listed
    #: ATM point alone supports) or "expected_payoff" (integrates the payoff
    #: profile against a density built from the listed OTM smile). Both are
    #: computed on every row regardless; this picks which lands in ``signal``.
    signal_mode: str = "breakeven_vol"
    #: Which benchmark ``signal`` uses: "listed" (the point of this module) or
    #: "otc" (the sector-matched swaption control, i.e. strategy 1 re-run on
    #: these structures). Both are computed on every row regardless.
    benchmark: str = "listed"
    #: Business days per year, for the annual-vol <-> daily-vol bridge. Applies
    #: identically to the curve breakeven, the listed quote and the swaption
    #: quote, which is what makes bp/day the common unit.
    business_days_per_year: float = 252.0

    # ---------------------------------------------------------- listed benchmark
    #: Which listed complex drives the SFR-mode functions. "SFR" is the only
    #: value they accept; the UST long-end mode is reached through
    #: :func:`build_longend_listed_panel`, which takes the constant-maturity
    #: panel explicitly rather than switching on this field -- the two modes
    #: consume different data shapes (full smile vs ATM-only constant maturity)
    #: and a single string switch would hide that.
    listed_source: str = "SFR"
    #: A listed contract is matched to the date only if its expiry is within this
    #: many days of ``as_of + horizon``. Measured on the SFR panel: 525 of 540
    #: dates match at 60 days, worst gap 45, median 23.
    listed_max_gap_days: float = 60.0
    #: Contracts closer to expiry than this are ignored -- a normal vol backed
    #: out of a nearly-intrinsic premium is numerically unstable.
    listed_min_tte_years: float = 0.02

    # ------------------------------------------------------------- OTC control
    #: The swaption node used as the sector-matched OTC control. 1Yx2Y, not
    #: JPM's 1Yx30Y: the point of the control is to isolate the OTC-vs-listed
    #: difference at FIXED sector, so it must match the curve legs' tenor and the
    #: listed option's expiry, not the note's long-end node.
    otc_expiry: str = "1Y"
    otc_tenor: str = "2Y"

    # ------------------------------------------------------------- entry rules
    #: The curve is CHEAP when
    #: ``breakeven_bp_per_day < benchmark_bp_per_day - entry_threshold_bp_per_day``
    #: and RICH when above by the same margin. 0.0 is the note's own rule (any
    #: divergence); a positive value opens a no-trade band.
    entry_threshold_bp_per_day: float = 0.0
    #: expected-payoff mode: cheap when ``E[payoff] > +threshold * package_dv01``.
    entry_threshold_bp: float = 0.0
    #: When False only the cheap (flattener) side trades. The note trades both:
    #: "when it is negative, we do the opposite."
    trade_when_rich: bool = True

    # ------------------------------------------------------------------ cohort
    #: How often a new overlapping cohort opens. Weekly here rather than strategy
    #: 1's monthly: the sample is 540 days rather than 1,900, and 2Y-tail
    #: forwards reprice in ~0.15 s against ~0.09 s for a 50Y spot leg, so the
    #: engine cost is affordable. It buys resolution, NOT independence --
    #: 1-year cohorts opened a week apart share ~98% of their holding window.
    cohort_freq: str = "weekly"
    #: Panel-build cadence, consumed by the caller, not by this module. Daily
    #: because the backtest lags the signal by one day and therefore needs the
    #: previous day's row, not the previous cohort's.
    signal_freq: str = "daily"
    #: Cohorts opened within ``horizon`` of the sample end stay LIVE and are
    #: marked, never force-closed. On a 2-year sample that is HALF the cohorts,
    #: which is the single biggest reason the P&L here is an illustration and not
    #: a strategy result.
    force_close_at_end: bool = False

    # ------------------------------------------------------------------- costs
    #: One-way transaction cost per leg-pair, bp of package DV01. Charged twice
    #: (in and out) at the unwind, which is the engine's only cost hook.
    cost_bp_one_way: float = 0.5

    # ---------------------------------------------------- UST long-end mode
    #: Structures the UST mode runs on. Ignored entirely by the SFR mode.
    longend_structures: Tuple[Tuple[str, str, str], ...] = LONG_END_STRUCTURES
    #: Constant maturities to compare at, in calendar days. All three are always
    #: computed -- the term-structure question is answered by reporting the
    #: answer at each, not by picking one. 180 exists in the harvest plan but is
    #: empty for every root, so it is not offered.
    longend_cm_days: Tuple[int, ...] = (30, 60, 90)
    #: Shift grid for the long-end curve regression. Strategy 1's own; see
    #: :data:`LONGEND_SHIFTS_BP` for why it is NOT the wide grid.
    longend_shifts_bp: Tuple[float, ...] = LONGEND_SHIFTS_BP
    #: The swaption node the stored strategy-1 panel was built against, and hence
    #: the OTC benchmark the long-end mode compares the listed one to. The note's
    #: own node -- unlike the SFR mode's 1Yx2Y control, this one does NOT need to
    #: be re-matched, because the whole question is whether the listed benchmark
    #: changes the verdict strategy 1 reached against exactly this node.
    longend_otc_expiry: str = "1Y"
    longend_otc_tenor: str = "30Y"
    #: Window for the UST mode. The constant-maturity panel and the swap curve
    #: both run 2019-01-02..2026-08-14, so unlike the SFR mode nothing is
    #: truncated: this is the full sample strategy 1 itself was measured on.
    longend_start: datetime.date = datetime.date(2019, 1, 1)
    longend_end: datetime.date = datetime.date(2026, 8, 14)

    # ------------------------------------------------------------------ window
    #: Defaults to the SFR listed panel's own span. The swap curve runs
    #: 2019-01-02 onward, so the SFR panel is the binding constraint on both ends.
    #: The UST mode uses ``longend_start`` / ``longend_end`` instead.
    start: datetime.date = datetime.date(2024, 7, 1)
    end: datetime.date = datetime.date(2026, 7, 28)

    def shifts(self) -> np.ndarray:
        return np.asarray(self.shifts_bp, dtype=float)

    def longend_shifts(self) -> np.ndarray:
        return np.asarray(self.longend_shifts_bp, dtype=float)

    def longend_curve_config(self) -> Strat1Config:
        """The :class:`Strat1Config` the STORED strategy-1 panel was built with.

        Used only by :func:`longend_curve_regression`, whose entire job is to
        prove that reusing that panel is exact. Every field that touches the
        payoff profile -- ``structures``, ``shifts_bp``, ``horizon``,
        ``package_dv01``, ``curve`` -- must therefore match strategy 1's
        defaults, not this module's SFR-tuned ones.
        """
        return Strat1Config(
            structures=self.longend_structures,
            curve=self.curve,
            package_dv01=self.package_dv01,
            horizon=self.horizon,
            horizon_years=self.horizon_years,
            shifts_bp=self.longend_shifts_bp,
            signal_mode="breakeven_vol",
            swaption_expiry=self.longend_otc_expiry,
            swaption_tenor=self.longend_otc_tenor,
            business_days_per_year=self.business_days_per_year,
            entry_threshold_bp_per_day=self.entry_threshold_bp_per_day,
            entry_threshold_bp=self.entry_threshold_bp,
            trade_when_rich=self.trade_when_rich,
            trade_straddle=False,
            cost_bp_one_way=self.cost_bp_one_way,
            start=self.longend_start,
            end=self.longend_end,
        )

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    def curve_config(self) -> Strat1Config:
        """The equivalent :class:`Strat1Config`, so strategy 1's kernel is reused.

        ``structure_profile``, ``breakeven_vol``, ``build_backtest`` and
        ``cohort_table`` are imported from ``strat1_curve_gamma`` unchanged and
        driven by this object. Nothing about the curve side of the calculation
        is reimplemented here -- if it were, a divergence between strat1 and
        strat1-listed would be un-diagnosable.
        """
        return Strat1Config(
            structures=self.structures,
            curve=self.curve,
            package_dv01=self.package_dv01,
            horizon=self.horizon,
            horizon_years=self.horizon_years,
            shifts_bp=self.shifts_bp,
            signal_mode=self.signal_mode,
            swaption_expiry=self.otc_expiry,
            swaption_tenor=self.otc_tenor,
            business_days_per_year=self.business_days_per_year,
            entry_threshold_bp_per_day=self.entry_threshold_bp_per_day,
            entry_threshold_bp=self.entry_threshold_bp,
            trade_when_rich=self.trade_when_rich,
            cohort_freq=self.cohort_freq,
            signal_freq=self.signal_freq,
            force_close_at_end=self.force_close_at_end,
            trade_straddle=False,
            cost_bp_one_way=self.cost_bp_one_way,
            start=self.start,
            end=self.end,
        )


# ---------------------------------------------------------------- signal panel


def listed_signal_row(
    pricer: Any,
    label: str,
    front_tenor: str,
    back_tenor: str,
    cfg: Strat1ListedConfig,
    *,
    listed: Optional[Mapping] = None,
    otc_atmf_bp: float = float("nan"),
    listed_smile: Optional[pd.DataFrame] = None,
    otc_smile: Optional[pd.DataFrame] = None,
    listed_weights: Optional[np.ndarray] = None,
    otc_weights: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """One (date, structure) row: the curve breakeven against BOTH benchmarks.

    ``listed`` is one row of :func:`listed_vol.listed_atm_series` as a mapping
    (``listed_atm_bp_day``, ``listed_symbol``, ``listed_tte``,
    ``listed_gap_days``, ...). ``otc_atmf_bp`` is the sector-matched swaption
    ATMF vol in bp/YEAR; it is converted here so the two benchmarks go through
    the identical annual->daily bridge.

    ``listed_weights`` / ``otc_weights`` accept a Breeden-Litzenberger density
    already evaluated on ``cfg.shifts()``. The density depends only on the date
    and the market, not on the structure, so the panel builder computes each once
    per date and reuses it across structures -- at ~0.14 s per density and five
    structures that is most of the per-date cost. Passing a smile instead is
    equivalent and is what a standalone caller should do.

    The row carries the curve breakeven once and every comparison derived from
    it, so the listed and OTC verdicts can never be computed off different
    profiles -- the single most likely way a "listed vs OTC" study fools itself.
    """
    prof = structure_profile(pricer, label, front_tenor, back_tenor,
                             cfg.curve_config(), direction=FLATTENER)
    be = breakeven_vol(
        prof.shifts_bp, prof.payoff_ccy,
        horizon_years=cfg.horizon_years,
        business_days_per_year=cfg.business_days_per_year,
    )

    listed = dict(listed or {})
    listed_day = float(listed.get("listed_atm_bp_day", float("nan")))
    otc_day = vol_bp_per_day(otc_atmf_bp, cfg.business_days_per_year)

    sig_listed = signal_from_breakeven(
        be, listed_day,
        threshold_bp_per_day=cfg.entry_threshold_bp_per_day,
        trade_when_rich=cfg.trade_when_rich,
    )
    sig_otc = signal_from_breakeven(
        be, otc_day,
        threshold_bp_per_day=cfg.entry_threshold_bp_per_day,
        trade_when_rich=cfg.trade_when_rich,
    )

    # Expected payoff under each market's own implied density. The listed smile
    # is a distribution of the 3M SOFR rate at the option's expiry, so it is
    # integrated over the option's OWN tte; the swaption smile over the horizon.
    ep_listed = _expected_payoff(
        prof.shifts_bp, prof.payoff_ccy, smile=listed_smile, weights=listed_weights,
        tte_years=float(listed.get("listed_tte", cfg.horizon_years) or cfg.horizon_years))
    ep_otc = _expected_payoff(
        prof.shifts_bp, prof.payoff_ccy, smile=otc_smile, weights=otc_weights,
        tte_years=cfg.horizon_years)

    sig_ep_listed = signal_from_expected_payoff(
        ep_listed, package_dv01=cfg.package_dv01,
        threshold_bp=cfg.entry_threshold_bp, trade_when_rich=cfg.trade_when_rich)
    sig_ep_otc = signal_from_expected_payoff(
        ep_otc, package_dv01=cfg.package_dv01,
        threshold_bp=cfg.entry_threshold_bp, trade_when_rich=cfg.trade_when_rich)

    row: Dict[str, Any] = {
        "structure": label,
        "carry_roll_bp": prof.carry_bp,
        "breakeven_vol_bp_yr": be.bp_per_year,
        "breakeven_vol_bp_day": be.bp_per_day,
        "breakeven_status": be.status,
        # -------- listed benchmark
        "listed_symbol": listed.get("listed_symbol"),
        "listed_expiry": listed.get("listed_expiry"),
        "listed_tte": listed.get("listed_tte", float("nan")),
        "listed_gap_days": listed.get("listed_gap_days", float("nan")),
        "listed_atm_bp_yr": listed.get("listed_atm_bp_yr", float("nan")),
        "listed_atm_bp_day": listed_day,
        # -------- OTC control
        "otc_atmf_bp_yr": float(otc_atmf_bp),
        "otc_atmf_bp_day": otc_day,
        #: OTC minus listed, bp/day. Positive = swaptions price MORE vol than the
        #: exchange. This is the basis that makes the two signals able to differ.
        "otc_minus_listed_bp_day": otc_day - listed_day,
        # -------- gaps, in the note's own unit
        "cheapness_vs_listed_bp_day": listed_day - be.bp_per_day,
        "cheapness_vs_otc_bp_day": otc_day - be.bp_per_day,
        # -------- signals
        "signal_listed": sig_listed,
        "signal_otc": sig_otc,
        "signal_ep_listed": sig_ep_listed,
        "signal_ep_otc": sig_ep_otc,
        "expected_payoff_listed_bp": (ep_listed / cfg.package_dv01
                                      if np.isfinite(ep_listed) else float("nan")),
        "expected_payoff_otc_bp": (ep_otc / cfg.package_dv01
                                   if np.isfinite(ep_otc) else float("nan")),
        "convex": is_convex(prof.shifts_bp, prof.convexity_ccy),
    }
    for s, v in zip(prof.shifts_bp, prof.payoff_bp):
        row[f"payoff_bp_{int(s):+d}"] = float(v)

    if cfg.signal_mode == "breakeven_vol":
        row["signal"] = sig_listed if cfg.benchmark == "listed" else sig_otc
    else:
        row["signal"] = sig_ep_listed if cfg.benchmark == "listed" else sig_ep_otc
    return row


def shift_density(
    smile: Optional[pd.DataFrame],
    shifts: Sequence[float],
    *,
    tte_years: float,
    min_points: int = 5,
) -> Optional[np.ndarray]:
    """Breeden-Litzenberger density of the terminal rate shift, on *shifts*.

    ``smile`` must carry ``offset_bp`` / ``vol_bp`` -- the shape both
    ``swaption_cube.smile_on`` and ``listed_vol.sfr_smile_on`` return, which is
    the whole reason the listed loader adopts the swaption cube's column names.
    Returns ``None`` when the smile is too sparse or too broken to differentiate,
    so the caller falls back to the breakeven signal rather than silently
    receiving a guess.
    """
    from RVUtils.ConvexityRV.swaption_cube import implied_shift_density

    if smile is None or len(smile) < min_points:
        return None
    if not np.isfinite(tte_years) or float(tte_years) <= 0:
        return None
    try:
        w = implied_shift_density(smile, shifts, tte_years=float(tte_years),
                                  min_points=min_points)
    except Exception:
        return None
    return w if np.isfinite(w).all() else None


def _expected_payoff(
    shifts: np.ndarray,
    payoff: np.ndarray,
    *,
    smile: Optional[pd.DataFrame] = None,
    weights: Optional[np.ndarray] = None,
    tte_years: float = 1.0,
) -> float:
    """E[payoff] under a supplied density, or one built from *smile*."""
    w = weights
    if w is None:
        w = shift_density(smile, shifts, tte_years=tte_years)
    if w is None:
        return float("nan")
    w = np.asarray(w, dtype=float)
    if w.shape != np.asarray(shifts).shape:
        return float("nan")
    return expected_payoff(shifts, payoff, w)


def build_listed_signal_panel(
    mdp: Any,
    cfg: Strat1ListedConfig,
    dates: Sequence[Any],
    *,
    listed_series: pd.DataFrame,
    listed_panel: Optional[pd.DataFrame] = None,
    otc_atmf: Optional[pd.Series] = None,
    otc_panel: Optional[pd.DataFrame] = None,
    progress_every: int = 25,
    log: Any = print,
) -> pd.DataFrame:
    """The full (date x structure) signal panel.

    ``listed_series``
        output of :func:`listed_vol.listed_atm_series` -- date-indexed, one
        horizon-matched listed contract per date.
    ``listed_panel``
        the full quote panel from :func:`listed_vol.load_sfr_panel`. Optional;
        supplied only when the expected-payoff signal is wanted, since it costs a
        Breeden-Litzenberger density per (date, structure).
    ``otc_atmf`` / ``otc_panel``
        the sector-matched swaption ATMF series and full smile panel from
        ``swaption_cube``.

    One curve build per date, shared across structures: the framework is
    per-structure but the curve is not, and rebuilding it per structure would
    multiply the cost for nothing. Measured cost on this universe: ~1.4 s for the
    curve plus ~0.15 s per structure, i.e. ~2 s per date and ~20 minutes for the
    540-date panel single-threaded.

    Dates on which no listed contract matches within ``listed_max_gap_days`` are
    still built -- the curve breakeven and the OTC comparison are valid there --
    and carry NaN listed columns, which makes them drop out of the listed signal
    by construction rather than by a filter someone has to remember to apply.
    """
    from RVUtils.ConvexityRV.swaption_cube import smile_on

    rows: List[Dict[str, Any]] = []
    idx = [pd.Timestamp(d) for d in dates]
    for i, ts in enumerate(idx):
        day = ts.date()
        try:
            pricer = mdp.get_data({"curve_name": cfg.curve, "timestamp": day})
        except Exception as exc:  # pragma: no cover - data gap
            log(f"  {day}: curve unavailable ({type(exc).__name__}: {exc})")
            continue
        if pricer is None:
            continue

        listed = (listed_series.loc[ts].to_dict()
                  if listed_series is not None and ts in listed_series.index else {})
        otc_v = float("nan")
        if otc_atmf is not None and ts in otc_atmf.index:
            otc_v = float(otc_atmf.loc[ts])

        # One density per market per date, shared across structures -- it depends
        # on the smile and the shift grid, neither of which is per-structure.
        shifts = cfg.shifts()
        l_w = None
        if listed_panel is not None and listed.get("listed_symbol"):
            try:
                l_smile = lv.sfr_smile_on(listed_panel, ts, str(listed["listed_symbol"]))
                l_w = shift_density(l_smile, shifts,
                                    tte_years=float(listed.get("listed_tte") or cfg.horizon_years))
            except Exception:
                l_w = None
        o_w = None
        if otc_panel is not None:
            try:
                o_smile = smile_on(otc_panel, day, cfg.otc_expiry, cfg.otc_tenor)
                o_w = shift_density(o_smile, shifts, tte_years=cfg.horizon_years)
            except Exception:
                o_w = None

        for label, ft, bt in cfg.structures:
            try:
                r = listed_signal_row(pricer, label, ft, bt, cfg, listed=listed,
                                      otc_atmf_bp=otc_v, listed_weights=l_w,
                                      otc_weights=o_w)
            except Exception as exc:  # pragma: no cover - data gap
                log(f"  {day} {label}: {type(exc).__name__}: {exc}")
                continue
            r["date"] = ts
            rows.append(r)
        if progress_every and (i + 1) % progress_every == 0:
            log(f"  listed signal panel {i + 1}/{len(idx)} ({day})", flush=True)

    if not rows:
        raise RuntimeError("listed signal panel is empty -- no curve resolved on any date")
    out = pd.DataFrame(rows)
    return out.set_index(["date", "structure"]).sort_index()


# --------------------------------------------------------------- reporting


def signal_distribution(
    panel: pd.DataFrame,
    *,
    benchmark: str = "listed",
) -> pd.DataFrame:
    """How often, and by how much, the curve is cheap against the benchmark.

    **This is the headline output**, not the P&L. The usable listed window is 540
    daily dates with a 1-year holding period, i.e. ~1 non-overlapping observation
    per structure; a Sharpe computed on that is a number, not evidence. The
    signal distribution uses every day and is a statement about pricing rather
    than about a trading rule, so it survives the short sample.

    One row per structure with the fraction of days cheap / rich / flat, the
    median gap in bp/day, and how often the two benchmarks DISAGREE -- which is
    the direct answer to "is this a relabelling of strategy 1".
    """
    b = str(benchmark).lower()
    if b not in ("listed", "otc"):
        raise ValueError("benchmark must be 'listed' or 'otc'")
    sig_col = f"signal_{b}"
    gap_col = f"cheapness_vs_{b}_bp_day"
    bench_col = "listed_atm_bp_day" if b == "listed" else "otc_atmf_bp_day"

    df = panel.reset_index()
    rows: List[Dict[str, Any]] = []
    for label, g in df.groupby("structure", sort=True):
        usable = g[np.isfinite(g[bench_col].to_numpy(dtype=float))]
        n = int(len(usable))
        s = usable[sig_col].to_numpy(dtype=float)
        both = usable[np.isfinite(usable["listed_atm_bp_day"].to_numpy(dtype=float))
                      & np.isfinite(usable["otc_atmf_bp_day"].to_numpy(dtype=float))]
        rows.append({
            "structure": label,
            "n_days": n,
            "frac_cheap": float(np.mean(s > 0)) if n else float("nan"),
            "frac_rich": float(np.mean(s < 0)) if n else float("nan"),
            "frac_flat": float(np.mean(s == 0)) if n else float("nan"),
            "frac_always_cheap": float(np.mean(usable["breakeven_status"] == "always_cheap")) if n else float("nan"),
            "frac_never_cheap": float(np.mean(usable["breakeven_status"] == "never_cheap")) if n else float("nan"),
            "median_breakeven_bp_day": float(np.nanmedian(
                _finite(usable["breakeven_vol_bp_day"]))) if n else float("nan"),
            "median_benchmark_bp_day": float(np.nanmedian(
                _finite(usable[bench_col]))) if n else float("nan"),
            "median_gap_bp_day": float(np.nanmedian(_finite(usable[gap_col]))) if n else float("nan"),
            "median_carry_bp": float(np.nanmedian(usable["carry_roll_bp"].to_numpy(dtype=float))) if n else float("nan"),
            "frac_convex": float(np.mean(usable["convex"].to_numpy(dtype=bool))) if n else float("nan"),
            "n_days_both_benchmarks": int(len(both)),
            "frac_signals_disagree": (float(np.mean(
                both["signal_listed"].to_numpy(dtype=float)
                != both["signal_otc"].to_numpy(dtype=float))) if len(both) else float("nan")),
            "median_otc_minus_listed_bp_day": (float(np.nanmedian(
                _finite(both["otc_minus_listed_bp_day"]))) if len(both) else float("nan")),
        })
    return pd.DataFrame(rows)


def _finite(s: pd.Series) -> np.ndarray:
    """Drop +/-inf as well as NaN. ``breakeven_vol_bp_day`` is legitimately
    ``inf`` on ``never_cheap`` days, and a median that swallows infinities is a
    median of a different variable."""
    a = s.to_numpy(dtype=float)
    return a[np.isfinite(a)]


def vol_basis_frame(panel: pd.DataFrame) -> pd.DataFrame:
    """Daily OTC-minus-listed ATM vol basis, bp/day, with the matched contract.

    The benchmark columns are identical across structures on a given date, so
    this collapses the panel to one row per date. Positive = the swaption market
    prices more vol than the exchange.
    """
    df = panel.reset_index()
    cols = ["date", "listed_symbol", "listed_expiry", "listed_tte", "listed_gap_days",
            "listed_atm_bp_yr", "listed_atm_bp_day",
            "otc_atmf_bp_yr", "otc_atmf_bp_day", "otc_minus_listed_bp_day"]
    have = [c for c in cols if c in df.columns]
    out = df[have].drop_duplicates(subset=["date"]).set_index("date").sort_index()
    return out


def long_end_reference_frame(
    strat1_panel: pd.DataFrame,
    start: Any,
    end: Any,
    *,
    business_days_per_year: float = 252.0,
) -> pd.DataFrame:
    """SUPERSEDED for the UST question; kept because the SFR notebook calls it.

    .. note::
       This function predates the constant-maturity UST harvest and its
       ``listed_benchmark = "unavailable"`` stamp is no longer true. It is kept
       verbatim so the SFR notebook and its assertions keep running; anything
       asking what the long end looks like against listed vol should call
       :func:`build_longend_listed_panel` instead.

    Strategy 1's long-end structures over the SFR listed window, as a NON-comparison.

    Reads the existing ``strat1_signal_panel.parquet`` rather than recomputing
    -- the curve side is identical and re-deriving it would create a second
    number that could disagree with the first for no reason. Restricted to the
    listed window so the two studies are on the same days.

    Every row is stamped ``listed_benchmark = "unavailable"``. The long end's
    natural listed benchmark is a UST bond option; there is no offline UST
    option history in this repo, and the only code path to one crawls a vendor
    per strike. So these rows carry the curve breakeven and the 1Yx30Y SWAPTION
    comparison strategy 1 already made, and no listed number at all. They are
    here to show what is missing, not to fill it.
    """
    df = strat1_panel.copy()
    if "date" not in df.columns:
        df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
    keep = [c for c in ["date", "structure", "carry_roll_bp", "breakeven_vol_bp_day",
                        "breakeven_status", "atmf_vol_bp_day", "signal_breakeven",
                        "convex"] if c in df.columns]
    out = df[keep].copy()
    out["listed_benchmark"] = "unavailable"
    out["listed_benchmark_reason"] = (
        "long-end structures require UST bond options; no offline UST "
        "futures-option SMILE panel exists (measured: 8 cached UST sabr_smile "
        "keys on 2 dates, Mar-2026). SFR options price the short end and would "
        "be a sector mismatch. SUPERSEDED for ATM vol: see "
        "build_longend_listed_panel."
    )
    return out.sort_values(["date", "structure"]).reset_index(drop=True)


# =============================================================================
#  UST long-end mode
# =============================================================================


def _as_curve_panel(strat1_panel: pd.DataFrame) -> pd.DataFrame:
    """Normalise the stored strategy-1 signal panel to a flat, typed frame."""
    df = strat1_panel.copy()
    if "date" not in df.columns or "structure" not in df.columns:
        df = df.reset_index()
    need = {"date", "structure", "breakeven_vol_bp_day", "breakeven_status",
            "atmf_vol_bp_day", "carry_roll_bp"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(
            f"strat1 panel is missing {sorted(missing)}; expected the frame written by "
            "strat1_curve_gamma.build_signal_panel (strat1_signal_panel.parquet)")
    df["date"] = pd.to_datetime(df["date"])
    df["structure"] = df["structure"].astype(str)
    return df


def build_longend_listed_panel(
    strat1_panel: pd.DataFrame,
    ust_panel: pd.DataFrame,
    cfg: Strat1ListedConfig,
    *,
    structures: Optional[Sequence[str]] = None,
    roles: Sequence[str] = ("primary", "alt", "control"),
) -> pd.DataFrame:
    """The long-end (date x structure x benchmark) panel. **The run that matters.**

    ``strat1_panel``
        strategy 1's OWN stored signal panel (``strat1_signal_panel.parquet``).
        The curve side is **reused, not recomputed**, and that is a deliberate
        choice rather than a shortcut: strategy 1's breakeven and this study's
        breakeven must be the same number, and re-deriving it would create a
        second one that could disagree for reasons having nothing to do with the
        listed benchmark. :func:`longend_curve_regression` proves the reuse is
        exact by rebuilding a sample of dates from the curve and asserting
        equality against the stored rows.
    ``ust_panel``
        ``listed_vol.load_ust_cm_panel()`` output.

    One row per (date, structure, benchmark), where a benchmark is a
    (root, constant maturity) pair drawn from ``listed_vol.UST_SECTOR_MAP`` for
    that structure -- so the primary, the alt and the deliberately-mismatched
    control all appear side by side and a reader cannot see one without the
    others. ``listed_role`` names which is which.

    ``structures`` restricts to a subset of ``cfg.longend_structures`` by label.
    ``roles`` selects which of ``primary`` / ``alt`` / ``control`` to build; it
    defaults to all three ON PURPOSE, because dropping the control is exactly how
    a sector comparison stops being checkable. Narrow it only for a targeted
    diagnostic, never for the headline table.

    Both comparisons are carried on every row from the SAME curve breakeven:

    ``cheapness_vs_listed_bp_day``  = listed  - breakeven
    ``cheapness_vs_otc_bp_day``     = 1Yx30Y  - breakeven
    ``otc_minus_listed_bp_day``     = 1Yx30Y  - listed

    The last one is the answer to the question this module exists to ask.
    Positive means swaptions price MORE vol than the exchange, i.e. swaptions
    were the expensive comparison; negative means the opposite.

    ``breakeven_vol_bp_day`` is legitimately ``0.0`` on ``always_cheap`` days and
    ``+inf`` on ``never_cheap`` days. Both are kept, and the signal is computed
    through ``strat1_curve_gamma.signal_from_breakeven`` -- the same kernel
    strategy 1 uses -- so an infinity is classified rather than dropped.
    """
    from RVUtils.ConvexityRV import listed_vol as lv

    cur = _as_curve_panel(strat1_panel)
    cur = cur[(cur["date"] >= pd.Timestamp(cfg.longend_start))
              & (cur["date"] <= pd.Timestamp(cfg.longend_end))]
    labels = ([str(s) for s in structures] if structures is not None
              else [lab for lab, _, _ in cfg.longend_structures])
    cur = cur[cur["structure"].isin(labels)]
    if cur.empty:
        raise ValueError(f"no stored strat1 rows for structures={labels} in "
                         f"{cfg.longend_start}..{cfg.longend_end}")

    rows: List[pd.DataFrame] = []
    for label in labels:
        bench = lv.ust_benchmarks_for(label)
        g = cur[cur["structure"] == label].set_index("date").sort_index()
        for role in roles:
            root = bench[role]
            for cm in cfg.longend_cm_days:
                ls = lv.ust_listed_atm_series(
                    ust_panel, root, cm,
                    business_days_per_year=cfg.business_days_per_year)
                j = g.join(ls, how="inner")
                if j.empty:
                    continue
                j = j.reset_index()
                j["listed_role"] = role
                j["listed_why"] = bench["why"]
                rows.append(j)
    if not rows:
        raise RuntimeError("long-end listed panel is empty -- no (date, root) overlap")

    out = pd.concat(rows, ignore_index=True)

    be = out["breakeven_vol_bp_day"].to_numpy(dtype=float)
    listed = out["listed_atm_bp_day"].to_numpy(dtype=float)
    otc = out["atmf_vol_bp_day"].to_numpy(dtype=float)

    out["otc_atmf_bp_day"] = otc
    out["otc_node"] = f"{cfg.longend_otc_expiry}x{cfg.longend_otc_tenor}"
    out["cheapness_vs_listed_bp_day"] = listed - be
    out["cheapness_vs_otc_bp_day"] = otc - be
    out["otc_minus_listed_bp_day"] = otc - listed
    out["signal_listed"] = [
        signal_from_breakeven(_be_result(b, s), l,
                              threshold_bp_per_day=cfg.entry_threshold_bp_per_day,
                              trade_when_rich=cfg.trade_when_rich)
        for b, s, l in zip(be, out["breakeven_status"].to_numpy(), listed)
    ]
    out["signal_otc"] = [
        signal_from_breakeven(_be_result(b, s), o,
                              threshold_bp_per_day=cfg.entry_threshold_bp_per_day,
                              trade_when_rich=cfg.trade_when_rich)
        for b, s, o in zip(be, out["breakeven_status"].to_numpy(), otc)
    ]
    return out.set_index(["date", "structure", "listed_symbol"]).sort_index()


def _be_result(bp_day: float, status: str):
    """Rehydrate a :class:`BreakevenResult` from the two stored columns.

    The stored panel keeps the breakeven and its status as plain columns, and
    ``signal_from_breakeven`` takes the dataclass. Reconstructing it -- rather
    than re-implementing the ``<``/``>`` comparison here -- is what keeps the
    long-end signal bit-identical to strategy 1's.

    At the default ``entry_threshold_bp_per_day = 0`` the status is *redundant*
    with the number: ``+inf`` compares rich and ``0.0`` compares cheap on their
    own. It stops being redundant the moment a threshold opens a no-trade band,
    because ``always_cheap`` means "carries positively, cheap against ANY vol"
    and must survive a band wider than the benchmark, whereas a raw ``0.0``
    would fall inside it and stand aside. Carrying the status is therefore not
    belt-and-braces -- it is the only thing that keeps a thresholded run
    correct, and ``test_signal_respects_never_cheap_branch`` pins exactly that.
    """
    from RVUtils.ConvexityRV.strat1_curve_gamma import BreakevenResult

    v = float(bp_day)
    return BreakevenResult(
        bp_per_year=v * float(np.sqrt(252.0)) if np.isfinite(v) else v,
        bp_per_day=v,
        status=str(status),
    )


def longend_signal_distribution(panel: pd.DataFrame) -> pd.DataFrame:
    """Cheap-share against listed AND against swaptions, per structure per benchmark.

    **The headline table.** One row per (structure, benchmark) carrying, side by
    side:

    * ``frac_cheap_vs_listed`` and ``frac_cheap_vs_otc`` -- the direct
      before/after of swapping the benchmark;
    * the median breakeven, the median of each benchmark, and the median gap;
    * ``median_otc_minus_listed_bp_day`` -- the vol basis, positive when
      swaptions price more vol than the exchange;
    * ``frac_signals_disagree`` -- how often the two benchmarks give opposite
      verdicts, which is the only number that can show the substitution was not
      a relabelling;
    * ``n_days`` and the window, because the per-root samples differ (US 1,917
      days, UL 1,662, TN 639) and comparing across roots without them compares
      different samples.

    Read alongside :func:`longend_benchmark_separation`: where the cheap-share is
    saturated at 1.00 it cannot discriminate between benchmarks, and the sector
    signal lives in the levels instead.
    """
    df = panel.reset_index()
    rows: List[Dict[str, Any]] = []
    for (label, sym), g in df.groupby(["structure", "listed_symbol"], sort=True):
        be = g["breakeven_vol_bp_day"].to_numpy(dtype=float)
        listed = g["listed_atm_bp_day"].to_numpy(dtype=float)
        otc = g["otc_atmf_bp_day"].to_numpy(dtype=float)
        ok_l = np.isfinite(listed)
        ok_o = np.isfinite(otc)
        both = ok_l & ok_o
        sl = g["signal_listed"].to_numpy(dtype=float)
        so = g["signal_otc"].to_numpy(dtype=float)
        rows.append({
            "structure": label,
            "listed_symbol": sym,
            "listed_role": g["listed_role"].iloc[0],
            "listed_root": g["listed_root"].iloc[0],
            "listed_cm_days": int(g["listed_cm_days"].iloc[0]),
            "listed_swap_point": g["listed_swap_point"].iloc[0],
            "n_days": int(ok_l.sum()),
            "first": g["date"].min().date().isoformat(),
            "last": g["date"].max().date().isoformat(),
            "frac_cheap_vs_listed": float(np.mean(sl[ok_l] > 0)) if ok_l.any() else float("nan"),
            "frac_cheap_vs_otc": float(np.mean(so[ok_o] > 0)) if ok_o.any() else float("nan"),
            "frac_always_cheap": float(np.mean(
                g["breakeven_status"].to_numpy()[ok_l] == "always_cheap")) if ok_l.any() else float("nan"),
            "frac_never_cheap": float(np.mean(
                g["breakeven_status"].to_numpy()[ok_l] == "never_cheap")) if ok_l.any() else float("nan"),
            "median_breakeven_bp_day": _med(be[ok_l]),
            "median_listed_bp_day": _med(listed[ok_l]),
            "median_otc_bp_day": _med(otc[ok_o]),
            "median_gap_vs_listed_bp_day": _med(
                g["cheapness_vs_listed_bp_day"].to_numpy(dtype=float)[ok_l]),
            "median_gap_vs_otc_bp_day": _med(
                g["cheapness_vs_otc_bp_day"].to_numpy(dtype=float)[ok_o]),
            "median_otc_minus_listed_bp_day": _med(
                g["otc_minus_listed_bp_day"].to_numpy(dtype=float)[both]),
            "n_days_both": int(both.sum()),
            "frac_signals_disagree": (float(np.mean(sl[both] != so[both]))
                                      if both.any() else float("nan")),
        })
    return pd.DataFrame(rows)


def _med(a: np.ndarray) -> float:
    """Median over finite entries only.

    ``breakeven_vol_bp_day`` is legitimately ``+inf`` on ``never_cheap`` days, and
    a median that swallows infinities is a median of a different variable. The
    COUNT of those days is reported separately as ``frac_never_cheap``, so
    dropping them here loses nothing.
    """
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return float(np.median(a)) if a.size else float("nan")


def longend_vol_basis(panel: pd.DataFrame) -> pd.DataFrame:
    """Daily swaption-minus-listed vol basis, bp/day, one column per benchmark.

    The benchmark columns do not depend on the structure, so this collapses to
    one row per date. Positive = the 1Yx30Y swaption prices more vol than the
    exchange contract.
    """
    df = panel.reset_index()
    keep = df.drop_duplicates(subset=["date", "listed_symbol"])
    wide = keep.pivot(index="date", columns="listed_symbol",
                      values="otc_minus_listed_bp_day").sort_index()
    wide["otc_atmf_bp_day"] = (keep.drop_duplicates("date")
                                   .set_index("date")["otc_atmf_bp_day"])
    return wide


def longend_term_structure_effect(panel: pd.DataFrame) -> pd.DataFrame:
    """How far the verdict moves across the 30/60/90-day constant maturities.

    Step 3 of the brief, answered rather than asserted. One row per
    (structure, root): the cheap-share and the median gap at each constant
    maturity, and the SPREAD of each across them.

    ``cheap_share_spread`` is the number to read. Where it is 0.0 the term
    structure cannot change the answer at all -- which on this universe is the
    case for the three saturated structures. Where it is not, the slope matters
    and the row says by how much.
    """
    df = panel.reset_index()
    rows: List[Dict[str, Any]] = []
    for (label, root), g in df.groupby(["structure", "listed_root"], sort=True):
        rec: Dict[str, Any] = {"structure": label, "listed_root": root,
                               "listed_role": g["listed_role"].iloc[0]}
        shares, gaps, levels = [], [], []
        for cm in sorted(g["listed_cm_days"].unique()):
            h = g[g["listed_cm_days"] == cm]
            ok = np.isfinite(h["listed_atm_bp_day"].to_numpy(dtype=float))
            s = float(np.mean(h["signal_listed"].to_numpy(dtype=float)[ok] > 0)) if ok.any() else float("nan")
            gp = _med(h["cheapness_vs_listed_bp_day"].to_numpy(dtype=float)[ok])
            lv_ = _med(h["listed_atm_bp_day"].to_numpy(dtype=float)[ok])
            rec[f"cheap_share_{int(cm)}"] = s
            rec[f"median_gap_{int(cm)}"] = gp
            rec[f"listed_bp_day_{int(cm)}"] = lv_
            rec[f"n_{int(cm)}"] = int(ok.sum())
            shares.append(s); gaps.append(gp); levels.append(lv_)
        rec["cheap_share_spread"] = _spread(shares)
        rec["median_gap_spread_bp_day"] = _spread(gaps)
        rec["listed_level_spread_bp_day"] = _spread(levels)
        rows.append(rec)
    return pd.DataFrame(rows)


def _spread(vals: Sequence[float]) -> float:
    """max - min over finite entries; NaN on an all-NaN group, without a warning.

    A ``never_cheap`` structure has ``breakeven = +inf``, so its cheapness gap is
    ``-inf`` on every date and the median of the finite entries is legitimately
    NaN. ``np.nanmax`` on that group raises "All-NaN axis encountered" and
    returns NaN anyway, which is a real answer wrapped in a spurious warning --
    and a warning that fires on ordinary data trains the reader to ignore
    warnings.
    """
    a = np.asarray(list(vals), dtype=float)
    a = a[np.isfinite(a)]
    return float(a.max() - a.min()) if a.size else float("nan")


def longend_benchmark_separation(panel: pd.DataFrame) -> pd.DataFrame:
    """Does the sector-matched benchmark differ from the mismatched control?

    The TY control exists to fail. But on a structure whose cheap-share is 1.00
    against every benchmark, cheap-share cannot fail -- so asking "does the
    control score worse?" of that column would answer "no" for a reason that has
    nothing to do with sector, and would quietly validate a broken comparison.

    This function therefore compares the primary against the control on the three
    quantities that CAN separate them, all at fixed constant maturity and on the
    intersection of their date windows:

    ``level_diff_bp_day``
        median primary benchmark minus median control benchmark. Sector shows up
        here first: a 7-year Treasury yield is more volatile than a 30-year one.
    ``gap_diff_bp_day``
        difference in the median cheapness gap -- the same information expressed
        as how much cheaper the curve looks against the wrong benchmark.
    ``cheap_share_diff``
        the verdict difference. Exactly 0.0 where saturated, which is the honest
        report and the reason the other two columns exist.
    ``r_change``
        correlation of the two benchmarks' DAILY CHANGES. Two roots that price
        genuinely different sectors do not move together tick for tick; a value
        near 1 would mean the control is not a control.
    """
    df = panel.reset_index()
    rows: List[Dict[str, Any]] = []
    for (label, cm), g in df.groupby(["structure", "listed_cm_days"], sort=True):
        prim = g[g["listed_role"] == "primary"]
        ctrl = g[g["listed_role"] == "control"]
        if prim.empty or ctrl.empty:
            continue
        p = prim.set_index("date")
        c = ctrl.set_index("date")
        common = p.index.intersection(c.index)
        if len(common) == 0:
            continue
        p, c = p.loc[common], c.loc[common]
        dp = p["listed_atm_bp_day"].diff()
        dc = c["listed_atm_bp_day"].diff()
        rows.append({
            "structure": label,
            "listed_cm_days": int(cm),
            "primary": p["listed_root"].iloc[0],
            "control": c["listed_root"].iloc[0],
            "n_common": int(len(common)),
            "primary_bp_day": _med(p["listed_atm_bp_day"].to_numpy(dtype=float)),
            "control_bp_day": _med(c["listed_atm_bp_day"].to_numpy(dtype=float)),
            "level_diff_bp_day": (_med(p["listed_atm_bp_day"].to_numpy(dtype=float))
                                  - _med(c["listed_atm_bp_day"].to_numpy(dtype=float))),
            "gap_diff_bp_day": (_med(p["cheapness_vs_listed_bp_day"].to_numpy(dtype=float))
                                - _med(c["cheapness_vs_listed_bp_day"].to_numpy(dtype=float))),
            "cheap_share_primary": float(np.mean(p["signal_listed"].to_numpy(dtype=float) > 0)),
            "cheap_share_control": float(np.mean(c["signal_listed"].to_numpy(dtype=float) > 0)),
            "cheap_share_diff": float(np.mean(p["signal_listed"].to_numpy(dtype=float) > 0)
                                      - np.mean(c["signal_listed"].to_numpy(dtype=float) > 0)),
            "r_level": float(p["listed_atm_bp_day"].corr(c["listed_atm_bp_day"])),
            "r_change": float(dp.corr(dc)),
        })
    return pd.DataFrame(rows)


def longend_curve_regression(
    mdp: Any,
    strat1_panel: pd.DataFrame,
    cfg: Strat1ListedConfig,
    dates: Sequence[Any],
    *,
    structures: Optional[Sequence[Tuple[str, str, str]]] = None,
    log: Any = print,
) -> pd.DataFrame:
    """Rebuild the payoff profile on *dates* and diff it against the stored panel.

    This is the tie-out that licenses the reuse in
    :func:`build_longend_listed_panel`. It resolves the package from the curve,
    reprices it across ``cfg.longend_shifts_bp``, re-solves the breakeven, and
    returns one row per (date, structure) with the maximum absolute difference in
    the payoff profile and the difference in carry and in breakeven against the
    stored row.

    A pass is ``max_payoff_diff_bp`` at machine precision. Anything larger means
    the stored panel and the live curve disagree, and the listed comparison built
    on top of it is measuring that disagreement instead of the market. Assert on
    the returned columns; do not eyeball them.
    """
    cur = _as_curve_panel(strat1_panel).set_index(["date", "structure"])
    structs = list(structures) if structures is not None else list(cfg.longend_structures)
    s1cfg = cfg.longend_curve_config()

    rows: List[Dict[str, Any]] = []
    for d in dates:
        ts = pd.Timestamp(d)
        try:
            pricer = mdp.get_data({"curve_name": cfg.curve, "timestamp": ts.date()})
        except Exception as exc:  # pragma: no cover - data gap
            log(f"  {ts.date()}: curve unavailable ({type(exc).__name__}: {exc})")
            continue
        if pricer is None:
            continue
        for label, ft, bt in structs:
            if (ts, label) not in cur.index:
                continue
            stored = cur.loc[(ts, label)]
            prof = structure_profile(pricer, label, ft, bt, s1cfg, direction=FLATTENER)
            be = breakeven_vol(prof.shifts_bp, prof.payoff_ccy,
                               horizon_years=cfg.horizon_years,
                               business_days_per_year=cfg.business_days_per_year)
            diffs = []
            for s, v in zip(prof.shifts_bp, prof.payoff_bp):
                col = f"payoff_bp_{int(s):+d}"
                if col in stored.index:
                    diffs.append(abs(float(v) - float(stored[col])))
            sb = float(stored["breakeven_vol_bp_day"])
            rows.append({
                "date": ts,
                "structure": label,
                "n_shifts_compared": len(diffs),
                "max_payoff_diff_bp": max(diffs) if diffs else float("nan"),
                "carry_stored_bp": float(stored["carry_roll_bp"]),
                "carry_rebuilt_bp": float(prof.carry_bp),
                "carry_diff_bp": abs(float(prof.carry_bp) - float(stored["carry_roll_bp"])),
                "breakeven_stored_bp_day": sb,
                "breakeven_rebuilt_bp_day": be.bp_per_day,
                "breakeven_diff_bp_day": (abs(be.bp_per_day - sb)
                                          if np.isfinite(be.bp_per_day) and np.isfinite(sb)
                                          else 0.0 if be.bp_per_day == sb else float("inf")),
                "status_stored": str(stored["breakeven_status"]),
                "status_rebuilt": be.status,
                "status_match": str(stored["breakeven_status"]) == be.status,
            })
    return pd.DataFrame(rows)


# =============================================================================
#  REAL LISTED CONTRACT mode -- re-exported from ``strat1_real_contracts``
#
#  The constant-maturity mode above is the CONTROL and is untouched. The
#  real-contract mode (``USM26`` instead of ``US_30``) lives in its own module
#  for the same reason ``listed_contracts`` is separate from ``listed_vol``: it
#  consumes a different data shape (a ragged per-contract panel with real
#  expiries and strikes, against a rectangular constant-maturity one) and folding
#  the two into one file would hide that difference behind a keyword argument.
#
#  The re-export is LAZY, via PEP 562's module ``__getattr__``, and that is not
#  style. ``strat1_threeway`` imports ``strat1_listed`` at module scope, and
#  ``strat1_real_contracts`` imports both -- so an eager ``from ... import`` here
#  would close the cycle ``strat1_listed -> strat1_real_contracts ->
#  strat1_threeway -> strat1_listed`` and every one of the three would fail to
#  import. Resolving on first attribute access breaks it, and callers see the
#  names on this module exactly as if they had been imported.
# =============================================================================

#: Names ``strat1_listed`` re-exports from ``strat1_real_contracts``. Listed
#: explicitly rather than deferring to that module's ``__all__`` so that adding a
#: private helper there cannot silently widen this module's surface.
_REAL_CONTRACT_EXPORTS: Tuple[str, ...] = (
    "RealContractConfig",
    "REAL_ROOTS",
    "REAL_ROOT_ROLE",
    "UNAVAILABLE_REAL_ROOTS",
    "TARGETS",
    "HEADLINE_TARGET",
    "HEADLINE_ROOT",
    "real_sector_note",
    "unavailable_root_penalty",
    "real_contract_atm_series",
    "build_longend_contract_panel",
    "contract_selection_report",
    "contract_roll_report",
    "ageing_table",
    "funded_straddle_frame",
    "funded_straddle_summary",
    "real_smile_frame",
    "smile_strike_offsets",
    "three_point_smile",
    "real_shift_density",
    "real_expected_payoff_frame",
    "cm_vs_real_table",
    "real_contract_verdict",
)

__all__ += list(_REAL_CONTRACT_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve the real-contract names on first access. See the block above."""
    if name in _REAL_CONTRACT_EXPORTS:
        from RVUtils.ConvexityRV import strat1_real_contracts as _rc

        return getattr(_rc, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> List[str]:
    """Keep tab-completion and ``dir()`` honest about the lazy names."""
    return sorted(set(globals()) | set(_REAL_CONTRACT_EXPORTS))
