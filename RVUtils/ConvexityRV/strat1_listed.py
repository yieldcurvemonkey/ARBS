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


Sector matching -- the design decision that makes this honest
-------------------------------------------------------------
Strategy 1's universe is LONG-END: 25Y/20Yx5Y, 30s/50s, 10Yx10Y/20Yx10Y. Its
natural listed benchmark is **UST bond options**, which do not exist offline in
this repo (see ``listed_vol.load_ust_panel`` for the measurement behind that).
The listed panel that does exist is **SFR (3M SOFR futures) options**, which
price the SHORT END.

Comparing a 30-year curve structure to a 3M-SOFR option would be a sector
mismatch and a fake result. So the universe here is a set of **SFR-sector
forward flatteners** -- :data:`SFR_STRUCTURES` -- chosen to sit inside the span
the SFR strip actually prices (1Y to 5Y forward-and-tail), and matched on every
date to the listed contract whose expiry is nearest the curve horizon.

The long-end structures are still reported, by
:func:`long_end_reference_frame`, but labelled ``listed benchmark unavailable``
and never given a listed comparison number.

Two residual mismatches remain and are not hidden:

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
The listed panel is 540 daily dates (2024-07-01..2026-07-28), of which 525 carry
a horizon-matched expiry. That is ~2 years, and with 1-year holding periods it
contains roughly **one** non-overlapping observation per structure. It cannot
support a Sharpe ratio, and this module's headline output is deliberately
:func:`signal_distribution` -- how often, and by how much, the curve is cheap
against listed vol -- with the cohort P&L reported as an illustration carrying
its own sample-size caveat.
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

#: Strategy 1's own long-end universe. Carried here only so the report can name
#: what it is NOT comparing: these have no offline listed benchmark, because the
#: instrument that would price them is a UST bond option.
LONG_END_STRUCTURES: Tuple[Tuple[str, str, str], ...] = (
    ("30Y/50Y", "30Y", "50Y"),
    ("20Yx5Y/25Yx5Y", "20Yx5Y", "25Yx5Y"),
    ("10Yx10Y/20Yx10Y", "10Yx10Y", "20Yx10Y"),
    ("5Y/30Y", "5Y", "30Y"),
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
    #: Which listed complex. "SFR" is the only one with offline data; "UST"
    #: raises ``listed_vol.ListedDataUnavailable`` by design rather than
    #: returning an empty frame that a table would render as a zero.
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

    # ------------------------------------------------------------------ window
    #: Defaults to the listed panel's own span. The swap curve runs 2019-01-02
    #: onward, so the listed panel is the binding constraint on both ends.
    start: datetime.date = datetime.date(2024, 7, 1)
    end: datetime.date = datetime.date(2026, 7, 28)

    def shifts(self) -> np.ndarray:
        return np.asarray(self.shifts_bp, dtype=float)

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
    """Strategy 1's long-end structures over the listed window, as a NON-comparison.

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
        "futures-option panel exists (measured: 8 cached UST sabr_smile keys on "
        "2 dates, Mar-2026). SFR options price the short end and would be a "
        "sector mismatch."
    )
    return out.sort_values(["date", "structure"]).reset_index(drop=True)
