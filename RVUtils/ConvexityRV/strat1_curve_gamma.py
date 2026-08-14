"""Strategy 1 -- the curve as a source of gamma, priced against swaptions.

Source: J.P. Morgan, **"An option by any other name: Sourcing cheap convexity in
the long end of the curve"** (Younger / Sarkar / Salem, 03-Feb-2017), restated in
"For cheap gamma, look to the long end" (23-Aug-2019) and given its fullest
written form in "Valuing convexity in the long end of the yield curve: A global
perspective" (09-Feb-2018).

The question the note asks, verbatim::

    "we require a framework for deciding whether long-end flatteners are a cheap
     or rich source of gamma compared to other instruments -- particularly
     options."

and its answer, also verbatim::

    "When the expected payoff on a flattener using an implied distribution
     extracted from swaption pricing is positive, the curve trade is the cheaper
     source of long gamma exposure. The same can also be said when the level of
     volatility priced into the curve is less than that implied by ATMF
     swaptions."

    "we initiate a flattener and sell 1Yx30Y ATMF swaption straddles to fund the
     carry on the position (i.e., sized such that the initiate premium intake is
     equal to the carry over the same 1-year horizon); when it is negative, we do
     the opposite."


What is measured, and what is approximated
------------------------------------------
The payoff profile is the **instantaneous** repricing of the struck package
across parallel shifts, with the horizon carry-and-roll added as a *level*::

    profile(s) = NPV(package | curve shifted s bp) - NPV(package | curve)
               + carry_and_roll_bp(horizon) * package_dv01

That is the shared ``curve_ops.payoff_profile(..., carry_ccy=...)`` contract, and
it is deliberate rather than lazy. The obvious alternative -- age the curve with
``rateslib.Curve.translate`` and reprice the struck swap there -- was measured
and is wrong: it returns 0.000 bp of carry on a DV01-neutral *forward* package
(the discount-factor renormalisation cancels) and -531.94 bp on a 1y-aged 30Y
payer (the swap's effective date falls behind the translated curve's initial
node, so a year of missing fixings gets extrapolated). ``curve_ops`` now refuses
that path outright. See its module docstring.

The cost of the approximation is that the *shape* is today's convexity rather
than the horizon's. The note itself draws the profile this way -- Exhibit 5's
footnote is "Net P/L for a spot 30s/50s flattener under parallel shifts in rate,
with coupons equal to the 1-year forward rates" -- and the shape term is second
order in the horizon while the carry term, which is exact here, is first order.

The regression table in ``tests/test_convexity_rv_strat1.py`` pins the shape on
2022-09-13 to 0.00 bp.


Which signal is primary, and why
--------------------------------
Both of the note's signals are implemented. The default is **breakeven vol**,
for a coverage reason measured on this repo's own swaption store over
2019-01-01..2026-08-31 (1900 store days, 1Yx30Y node):

======================  ==========  ==========================================
series                  coverage    available from
======================  ==========  ==========================================
ATMF vol                  97.8%     2015-10-08
full OTM smile            83.9%     **2020-03-25**
======================  ==========  ==========================================

The expected-payoff signal needs the OTM wings to build a Breeden-Litzenberger
density, so it cannot run at all before 2020-03-25 -- it would silently drop the
whole of 2019 including the repo-rate spike and the COVID crash. The
breakeven-vol signal needs only the ATMF point and runs over the entire window.
Set ``signal_mode="expected_payoff"`` to switch; the panel computes both
regardless so the two can be compared on their common sample.


Sign convention (established empirically, not read off the risk-weight code)
---------------------------------------------------------------------------
::

    OUTRIGHT bpv > 0  =  PAYER
    CURVE    bpv < 0  =  FLATTENER (pay front, receive back)  =  LONG convexity
    CURVE    bpv > 0  =  STEEPENER                            =  SHORT convexity

Every notebook that uses this module re-verifies it at execution time.
"""

from __future__ import annotations

import dataclasses
import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.curve_ops import payoff_profile
from RVUtils.ConvexityRV.payoff import (
    breakeven_vol_bp_per_year,
    expected_payoff,
    normal_pdf_weights,
)

__all__ = [
    "Strat1Config",
    "DEFAULT_STRUCTURES",
    "BreakevenResult",
    "StructureProfile",
    "FLATTENER",
    "STEEPENER",
    "resolve_package",
    "package_carry_roll_bp",
    "structure_profile",
    "breakeven_vol",
    "vol_bp_per_day",
    "is_convex",
    "signal_from_breakeven",
    "signal_from_expected_payoff",
    "atmf_straddle_premium_bp",
    "straddle_dv01_for_carry",
    "cohort_dates",
    "signal_row",
    "build_signal_panel",
    "build_backtest",
    "cohort_table",
]


#: ``bpv`` sign that produces a flattener (pay the front leg, receive the back).
FLATTENER = -1.0
#: ``bpv`` sign that produces a steepener.
STEEPENER = +1.0


#: (label, front_tenor, back_tenor). The first two are the pair JPM's Exhibit 5
#: reports side by side; the third and fourth are the note's other named
#: forward/spot comparisons and are carried so the ordering claim has more than
#: one witness. Forward notation "AYxBY" = a B-year swap starting in A years.
DEFAULT_STRUCTURES: Tuple[Tuple[str, str, str], ...] = (
    ("30Y/50Y", "30Y", "50Y"),                    # JPM Exhibit 5, spot column
    ("20Yx5Y/25Yx5Y", "20Yx5Y", "25Yx5Y"),        # JPM Exhibit 5, "25Y/20Yx5Y"
    ("10Yx10Y/20Yx10Y", "10Yx10Y", "20Yx10Y"),    # the 2019 note's forward pair
    ("5Y/30Y", "5Y", "30Y"),                      # spot control, heavy negative carry
)


@dataclass(frozen=True)
class Strat1Config:
    """Every knob of strategy 1. Defaults reproduce the note as closely as the
    data allows; nothing here is tuned on the backtest's own output."""

    # ---------------------------------------------------------------- universe
    #: (label, front_tenor, back_tenor) triples. Front is the SHORTER-dated leg;
    #: a flattener pays it and receives the back leg.
    structures: Tuple[Tuple[str, str, str], ...] = DEFAULT_STRUCTURES
    #: Curve to build every leg on.
    curve: str = "USD-SOFR-1D"
    #: Package risk. Both legs are struck to this |pv01|, so the package is
    #: DV01-neutral by construction and all P&L is reported in bp of this.
    package_dv01: float = 100_000.0

    # ------------------------------------------------------------------ signal
    #: Holding period AND the horizon the carry-and-roll and the vol comparison
    #: are measured over. The note: "we use 1Yx30Y swaptions for a 1-year
    #: horizon and assuming parallel shifts in rates."
    horizon: str = "1Y"
    #: The same horizon as a year fraction, for the vol scaling. Kept separate
    #: from ``horizon`` because that one is a rateslib tenor string.
    horizon_years: float = 1.0
    #: Terminal parallel shifts, bp. The note's Exhibit 3 axis runs -250..+250.
    #: Deliberately UNEVENLY spaced -- dense near the money where the profile
    #: curves, sparse in the wings where it is nearly linear.
    shifts_bp: Tuple[float, ...] = (-250.0, -200.0, -150.0, -100.0, -50.0, -25.0,
                                    0.0, 25.0, 50.0, 100.0, 150.0, 200.0, 250.0)
    #: "breakeven_vol" (default -- ATMF only, full window) or "expected_payoff"
    #: (needs the OTM smile, so only from 2020-03-25). See the module docstring.
    signal_mode: str = "breakeven_vol"
    #: The swaption node the curve is priced against. The note uses 1Yx30Y.
    swaption_expiry: str = "1Y"
    swaption_tenor: str = "30Y"
    #: Business days per year, for annual-vol <-> daily-vol conversion.
    business_days_per_year: float = 252.0

    # ------------------------------------------------------------- entry rules
    #: breakeven-vol mode: the curve is CHEAP when
    #: ``breakeven_bp_per_day < atmf_bp_per_day - entry_threshold_bp_per_day``
    #: and RICH when it is above by the same margin. A positive threshold
    #: creates a no-trade band; 0.0 is the note's own rule (any divergence).
    entry_threshold_bp_per_day: float = 0.0
    #: expected-payoff mode: cheap when ``E[payoff] > +threshold * package_dv01``
    #: (i.e. threshold is in bp of package DV01), rich when below ``-threshold``.
    entry_threshold_bp: float = 0.0
    #: When False, only the cheap (flattener) side is traded and rich days are
    #: flat. The note trades both: "when it is negative, we do the opposite."
    trade_when_rich: bool = True

    # ------------------------------------------------------------------ cohort
    #: How often a new overlapping cohort is opened. JPM initiate DAILY and hold
    #: a year, i.e. ~250 concurrent cohorts. Measured engine cost here is ~0.030 s
    #: per cohort per mark for the 5Y-tail forward structures and ~0.090 s for the
    #: spot ones (a 50Y leg has ten times the cashflows of a 25Yx5Y), so over 1,900
    #: marks: daily is ~40 h for 30s/50s, weekly ~2.5 h, monthly ~35 min. Monthly
    #: is the default for that reason and no other; "weekly"/"daily" are available
    #: and change nothing about the strategy.
    #:
    #: The statistical cost is small and worth stating: 1-year cohorts opened a
    #: week apart share ~98% of their holding window, so weekly entries do not
    #: supply ~4x the independent observations that their count suggests. Either
    #: way the sample contains ~7.6 non-overlapping years.
    cohort_freq: str = "monthly"
    #: Panel-build cadence, consumed by the CALLER (``_strat1_build.py`` / the
    #: notebook), not by anything in this module. It is daily because the
    #: backtest lags the signal by one day and therefore needs the previous
    #: *day's* row, not the previous cohort's; at ~3.6 s per day for four
    #: structures the full 1,908-day panel is ~2 h single-threaded and ~15 min
    #: in twelve parallel date chunks.
    signal_freq: str = "daily"
    #: Cohorts opened within ``horizon`` of the sample end are still LIVE at the
    #: end. They are marked, never force-closed; closed-cohort statistics and
    #: full-MTM equity are reported separately.
    force_close_at_end: bool = False

    # ------------------------------------------------------------- straddle leg
    #: Trade the funding straddle. Default OFF: the note sizes the straddle so
    #: its premium intake equals the package's carry over the horizon, and for
    #: the forward structures carry is ~0 (measured: +0.006 bp on 2022-09-13 for
    #: 20Yx5Y/25Yx5Y), so the straddle notional is ~0 and it is pure noise. It
    #: matters only for the negative-carry spot structures.
    trade_straddle: bool = False

    # ------------------------------------------------------------------- costs
    #: One-way transaction cost per leg-pair, bp of package DV01. Charged twice
    #: (in and out) at the unwind, which is the engine's only cost hook.
    cost_bp_one_way: float = 0.5

    # ------------------------------------------------------------------ window
    start: datetime.date = datetime.date(2019, 1, 1)
    end: datetime.date = datetime.date(2026, 8, 14)

    def shifts(self) -> np.ndarray:
        return np.asarray(self.shifts_bp, dtype=float)

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# --------------------------------------------------------------------- package


def resolve_package(
    pricer: Any,
    front_tenor: str,
    back_tenor: str,
    *,
    package_dv01: float,
    direction: float = FLATTENER,
    curve: str = "USD-SOFR-1D",
) -> Tuple[List[Any], List[float], List[Any]]:
    """Build a DV01-neutral two-leg curve package on *pricer*'s curve.

    ``direction`` is the SIGN applied to ``bpv``: ``FLATTENER`` (-1) pays the
    front leg and receives the back, ``STEEPENER`` (+1) does the reverse. The
    CURVE structure constrains the BACK leg to ``bpv`` and solves the front leg's
    notional off pv01, so both legs come back with |pv01| == ``package_dv01``.

    Returns ``(raw_legs, risk_weights, resolved_legs)``. The raw legs carry the
    unsigned notionals the value map expects; the resolved legs carry the signed
    notionals the repricing kernel needs.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    q = IRSwapQuery(
        structure=IRSwapStructure.CURVE,
        value=IRSwapValue.NPV,
        curve=curve,
        structure_kwargs={
            "front_tenor": front_tenor,
            "back_tenor": back_tenor,
            "bpv": float(direction) * float(package_dv01),
            # risk_weights is MUTATED in place by the structure builder, so a
            # fresh list per call is required -- a shared default would flip
            # sign on every second call.
            "risk_weights": [1.0, 1.0],
        },
    )
    raw, weights = q.resolve_package(pricer_or_curve=pricer)
    resolved = [pricer.resolve_pricable(s, risk_weight=w) for s, w in zip(raw, weights)]
    return list(raw), list(weights), resolved


def package_carry_roll_bp(
    pricer: Any,
    raw_legs: Sequence[Any],
    weights: Sequence[float],
    horizon: str = "1Y",
) -> float:
    """Package carry-and-roll over *horizon*, bp of package DV01.

    Mirrors ``IRSwapValueFunctionMap._carry_and_roll_bps_running`` exactly:
    ``sum(risk_weight_i * carry_and_roll_bps_running(leg_i, horizon))``. Verified
    on 2022-09-13 against the pinned values -- +0.0061 bp for the 20Yx5Y/25Yx5Y
    flattener, -20.6697 bp for 5Y/30Y.

    Positive means the package earns carry; a long-gamma flattener normally does
    not, which is the note's "no free lunch".
    """
    return float(sum(
        float(w) * float(pricer.carry_and_roll_bps_running(leg, horizon))
        for leg, w in zip(raw_legs, weights)
    ))


@dataclass(frozen=True)
class StructureProfile:
    """One structure, one day: the payoff profile and its carry."""

    label: str
    shifts_bp: np.ndarray
    #: P&L in currency across ``shifts_bp``, carry included as a level.
    payoff_ccy: np.ndarray
    #: Carry-and-roll over the horizon, bp of package DV01.
    carry_bp: float
    #: The same profile with carry stripped out -- pure convexity shape.
    convexity_ccy: np.ndarray
    package_dv01: float

    @property
    def payoff_bp(self) -> np.ndarray:
        return self.payoff_ccy / self.package_dv01

    @property
    def convexity_bp(self) -> np.ndarray:
        return self.convexity_ccy / self.package_dv01


def structure_profile(
    pricer: Any,
    label: str,
    front_tenor: str,
    back_tenor: str,
    cfg: Strat1Config,
    *,
    direction: float = FLATTENER,
) -> StructureProfile:
    """Payoff profile of one structure on *pricer*'s day.

    Always priced for the direction given (default: the flattener, which is the
    long-gamma side and the one the note's signal is written about). The
    steepener's profile is the exact negation, so the panel stores the flattener
    and the backtest flips the sign when the signal says rich.
    """
    raw, weights, resolved = resolve_package(
        pricer, front_tenor, back_tenor,
        package_dv01=cfg.package_dv01, direction=direction, curve=cfg.curve,
    )
    carry_bp = package_carry_roll_bp(pricer, raw, weights, cfg.horizon)
    shifts = cfg.shifts()
    convexity = payoff_profile(pricer, resolved, shifts, carry_ccy=0.0)
    return StructureProfile(
        label=label,
        shifts_bp=shifts,
        payoff_ccy=convexity + carry_bp * cfg.package_dv01,
        carry_bp=carry_bp,
        convexity_ccy=convexity,
        package_dv01=cfg.package_dv01,
    )


# ---------------------------------------------------------------------- signal


@dataclass(frozen=True)
class BreakevenResult:
    """Breakeven vol with the no-root case classified rather than swallowed.

    ``breakeven_vol_bp_per_year`` returns NaN whenever the expected payoff has no
    sign change on the bracket, and that single NaN covers two OPPOSITE states:

    ``always_cheap``
        the payoff is positive at zero vol -- i.e. the package carries POSITIVELY
        -- so it never needs volatility to break even. Breakeven vol is 0 and the
        curve is cheap against any swaption vol whatsoever.

    ``never_cheap``
        the payoff is still negative at 1000 bp/yr. Breakeven vol is +inf and the
        curve is rich against any swaption vol whatsoever.

    Collapsing both to NaN and dropping them would delete exactly the days the
    note cares most about (JPM's forward structure is "100% cheap curve gamma",
    which is this ``always_cheap`` branch), and would do it asymmetrically.
    """

    bp_per_year: float
    bp_per_day: float
    status: str  # "root" | "always_cheap" | "never_cheap" | "undefined"

    @property
    def ok(self) -> bool:
        return self.status != "undefined"


def breakeven_vol(
    shifts: Sequence[float],
    payoff: Sequence[float],
    *,
    horizon_years: float = 1.0,
    business_days_per_year: float = 252.0,
    lo: float = 1.0,
    hi: float = 1000.0,
) -> BreakevenResult:
    """The note's "volatility priced into the curve", with the NaN branches split.

        "we are estimating the level of normal daily volatility in rates that is
         sufficient to offset the carry costs on a given curve trade."
    """
    x = np.asarray(list(shifts), dtype=float)
    p = np.asarray(list(payoff), dtype=float)
    if not np.isfinite(p).all():
        return BreakevenResult(float("nan"), float("nan"), "undefined")

    root = breakeven_vol_bp_per_year(x, p, horizon_years=horizon_years, lo=lo, hi=hi)
    if np.isfinite(root):
        return BreakevenResult(float(root), float(root / math.sqrt(business_days_per_year)), "root")

    sqrt_t = math.sqrt(max(horizon_years, 1e-12))
    f_lo = expected_payoff(x, p, normal_pdf_weights(x, lo * sqrt_t))
    f_hi = expected_payoff(x, p, normal_pdf_weights(x, hi * sqrt_t))
    if not (np.isfinite(f_lo) and np.isfinite(f_hi)):
        return BreakevenResult(float("nan"), float("nan"), "undefined")
    if f_lo > 0:
        return BreakevenResult(0.0, 0.0, "always_cheap")
    if f_hi < 0:
        return BreakevenResult(float("inf"), float("inf"), "never_cheap")
    return BreakevenResult(float("nan"), float("nan"), "undefined")


def vol_bp_per_day(vol_bp_annual: float, business_days_per_year: float = 252.0) -> float:
    """Annual normal vol in bp -> the note's bp/day unit."""
    v = float(vol_bp_annual)
    if not np.isfinite(v):
        return float("nan")
    return v / math.sqrt(business_days_per_year)


def is_convex(shifts: Sequence[float], payoff: Sequence[float], *, tol: float = 0.0) -> bool:
    """True when the payoff is convex on a POSSIBLY UNEVEN grid.

    The shift grid is deliberately uneven (25 bp steps near the money, 50 bp in
    the wings), so a plain second difference of ``payoff`` is not a curvature
    test -- it mixes step sizes and can report a genuinely convex profile as
    concave. Convexity on an uneven grid is: the divided differences
    ``dP/ds`` are non-decreasing.
    """
    x = np.asarray(list(shifts), dtype=float)
    p = np.asarray(list(payoff), dtype=float)
    if x.size < 3 or not np.isfinite(p).all():
        return False
    order = np.argsort(x)
    x, p = x[order], p[order]
    slope = np.diff(p) / np.diff(x)
    return bool(np.all(np.diff(slope) >= -abs(tol)))


def signal_from_breakeven(
    be: BreakevenResult,
    atmf_bp_per_day: float,
    *,
    threshold_bp_per_day: float = 0.0,
    trade_when_rich: bool = True,
) -> float:
    """+1 = curve is CHEAP gamma (flattener), -1 = RICH (steepener), 0 = stand aside.

        "The same can also be said when the level of volatility priced into the
         curve is less than that implied by ATMF swaptions."
    """
    a = float(atmf_bp_per_day)
    if not np.isfinite(a) or be.status == "undefined":
        return 0.0
    if be.status == "always_cheap":
        return 1.0
    if be.status == "never_cheap":
        return -1.0 if trade_when_rich else 0.0
    t = abs(float(threshold_bp_per_day))
    if be.bp_per_day < a - t:
        return 1.0
    if be.bp_per_day > a + t:
        return -1.0 if trade_when_rich else 0.0
    return 0.0


def signal_from_expected_payoff(
    ep_ccy: float,
    *,
    package_dv01: float,
    threshold_bp: float = 0.0,
    trade_when_rich: bool = True,
) -> float:
    """+1 / -1 / 0 from the expected payoff under the swaption-implied density.

        "When the expected payoff on a flattener using an implied distribution
         extracted from swaption pricing is positive, the curve trade is the
         cheaper source of long gamma exposure."
    """
    v = float(ep_ccy)
    if not np.isfinite(v):
        return 0.0
    t = abs(float(threshold_bp)) * float(package_dv01)
    if v > t:
        return 1.0
    if v < -t:
        return -1.0 if trade_when_rich else 0.0
    return 0.0


# -------------------------------------------------------------- straddle sizing


def atmf_straddle_premium_bp(vol_bp_annual: float, tte_years: float = 1.0) -> float:
    """ATMF normal-model straddle premium, in bp of RATE per unit of annuity.

    Bachelier at the forward: call = put = sigma*sqrt(T)/sqrt(2*pi), so the
    straddle is ``sqrt(2/pi) * sigma * sqrt(T)`` ~= ``0.7979 * sigma * sqrt(T)``.
    Multiplying by the underlying swap's annuity (its $ per bp) turns it into
    currency, which is what makes the sizing below a pure DV01 statement and
    independent of the swaption MDP.
    """
    s = float(vol_bp_annual)
    if not np.isfinite(s) or s <= 0 or tte_years <= 0:
        return float("nan")
    return float(math.sqrt(2.0 / math.pi) * s * math.sqrt(float(tte_years)))


def straddle_dv01_for_carry(
    carry_ccy: float,
    vol_bp_annual: float,
    *,
    tte_years: float = 1.0,
) -> float:
    """Straddle size, expressed as the underlying swap's DV01, that intakes
    exactly ``|carry_ccy|`` of premium.

        "sized such that the initiate premium intake is equal to the carry over
         the same 1-year horizon"

    Returns $ of underlying DV01. Multiply by the 1Yx30Y swap's notional-per-DV01
    to get a notional. NaN when the vol is missing.
    """
    prem_bp = atmf_straddle_premium_bp(vol_bp_annual, tte_years)
    if not np.isfinite(prem_bp) or prem_bp <= 0:
        return float("nan")
    return float(abs(float(carry_ccy)) / prem_bp)


# --------------------------------------------------------------------- cohorts


def cohort_dates(dates: Sequence[Any], freq: str = "weekly") -> List[datetime.date]:
    """Sub-sample *dates* (already sorted business days) at the cohort cadence.

    "weekly"/"monthly" take the FIRST available grid day of each ISO week /
    calendar month, so a holiday shifts the cohort rather than deleting it.
    """
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates]).sort_values()
    if len(idx) == 0:
        return []
    f = str(freq).lower()
    if f == "daily":
        keep = idx
    elif f == "weekly":
        key = pd.Series(idx.isocalendar().year.to_numpy() * 100
                        + idx.isocalendar().week.to_numpy(), index=idx)
        keep = idx[~key.duplicated(keep="first").to_numpy()]
    elif f == "monthly":
        key = pd.Series(idx.year * 100 + idx.month, index=idx)
        keep = idx[~key.duplicated(keep="first").to_numpy()]
    else:
        raise ValueError(f"cohort_freq must be daily/weekly/monthly, got {freq!r}")
    return [d.date() for d in keep]


def _first_on_or_after(idx: pd.DatetimeIndex, target: pd.Timestamp) -> Optional[pd.Timestamp]:
    pos = idx.searchsorted(target, side="left")
    if pos >= len(idx):
        return None
    return idx[pos]


def cohort_schedule(
    grid_dates: Sequence[Any],
    entries: Sequence[Any],
    horizon: str = "1Y",
) -> List[Tuple[datetime.date, Optional[datetime.date]]]:
    """(entry, exit) pairs. ``exit is None`` => still LIVE at the sample end.

    Overlapping cohorts are the point of the design: JPM initiate daily and hold
    one year, so at steady state ~250 are open at once. Cohorts opened inside the
    last ``horizon`` of the sample have no exit and are NOT force-closed -- doing
    so would mark a set of 1-year trades at whatever partial horizon the sample
    happened to end on and mix them into the closed-trade statistics.
    """
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in grid_dates]).sort_values()
    n = int(str(horizon).upper().rstrip("Y") or 1) if str(horizon).upper().endswith("Y") else None
    out: List[Tuple[datetime.date, Optional[datetime.date]]] = []
    for e in entries:
        e_ts = pd.Timestamp(e)
        if n is not None:
            target = e_ts + pd.DateOffset(years=n)
        else:
            target = e_ts + pd.Timedelta(str(horizon))
        x = _first_on_or_after(idx, target)
        out.append((e_ts.date(), None if x is None else x.date()))
    return out


# ---------------------------------------------------------------- signal panel


def signal_row(
    pricer: Any,
    label: str,
    front_tenor: str,
    back_tenor: str,
    cfg: Strat1Config,
    *,
    atmf_vol_bp: float = float("nan"),
    smile: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """One (date, structure) row of the signal panel: both of the note's signals."""
    from RVUtils.ConvexityRV.swaption_cube import implied_shift_density

    prof = structure_profile(pricer, label, front_tenor, back_tenor, cfg, direction=FLATTENER)
    be = breakeven_vol(
        prof.shifts_bp, prof.payoff_ccy,
        horizon_years=cfg.horizon_years,
        business_days_per_year=cfg.business_days_per_year,
    )
    atmf_day = vol_bp_per_day(atmf_vol_bp, cfg.business_days_per_year)

    ep = float("nan")
    if smile is not None and len(smile) >= 5:
        w = implied_shift_density(smile, prof.shifts_bp, tte_years=cfg.horizon_years)
        ep = expected_payoff(prof.shifts_bp, prof.payoff_ccy, w)

    sig_be = signal_from_breakeven(
        be, atmf_day,
        threshold_bp_per_day=cfg.entry_threshold_bp_per_day,
        trade_when_rich=cfg.trade_when_rich,
    )
    sig_ep = signal_from_expected_payoff(
        ep, package_dv01=cfg.package_dv01,
        threshold_bp=cfg.entry_threshold_bp,
        trade_when_rich=cfg.trade_when_rich,
    )
    row: Dict[str, Any] = {
        "structure": label,
        "carry_roll_bp": prof.carry_bp,
        "breakeven_vol_bp_yr": be.bp_per_year,
        "breakeven_vol_bp_day": be.bp_per_day,
        "breakeven_status": be.status,
        "atmf_vol_bp_yr": float(atmf_vol_bp),
        "atmf_vol_bp_day": atmf_day,
        "expected_payoff_ccy": ep,
        "expected_payoff_bp": ep / cfg.package_dv01 if np.isfinite(ep) else float("nan"),
        "signal_breakeven": sig_be,
        "signal_expected_payoff": sig_ep,
        "convex": is_convex(prof.shifts_bp, prof.convexity_ccy),
        "straddle_dv01": straddle_dv01_for_carry(
            prof.carry_bp * cfg.package_dv01, atmf_vol_bp, tte_years=cfg.horizon_years),
    }
    for s, v in zip(prof.shifts_bp, prof.payoff_bp):
        row[f"payoff_bp_{int(s):+d}"] = float(v)
    row["signal"] = sig_be if cfg.signal_mode == "breakeven_vol" else sig_ep
    return row


def build_signal_panel(
    mdp: Any,
    cfg: Strat1Config,
    dates: Sequence[Any],
    *,
    atmf_vol: Optional[pd.Series] = None,
    vol_panel: Optional[pd.DataFrame] = None,
    progress_every: int = 25,
    log: Any = print,
) -> pd.DataFrame:
    """The full (date x structure) signal panel.

    One curve build per date, shared across structures -- the note's framework is
    per-structure but the curve is not, and rebuilding it per structure would
    triple the cost for nothing.
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
        av = float("nan")
        if atmf_vol is not None and ts in atmf_vol.index:
            av = float(atmf_vol.loc[ts])
        sm = None
        if vol_panel is not None:
            try:
                sm = smile_on(vol_panel, day, cfg.swaption_expiry, cfg.swaption_tenor)
            except Exception:
                sm = None
        for label, ft, bt in cfg.structures:
            try:
                r = signal_row(pricer, label, ft, bt, cfg, atmf_vol_bp=av, smile=sm)
            except Exception as exc:  # pragma: no cover - data gap
                log(f"  {day} {label}: {type(exc).__name__}: {exc}")
                continue
            r["date"] = ts
            rows.append(r)
        if progress_every and (i + 1) % progress_every == 0:
            log(f"  signal panel {i + 1}/{len(idx)} ({day})", flush=True)
    if not rows:
        raise RuntimeError("signal panel is empty -- no curve resolved on any date")
    out = pd.DataFrame(rows)
    return out.set_index(["date", "structure"]).sort_index()


# -------------------------------------------------------------------- backtest


def build_backtest(
    mdp: Any,
    cfg: Strat1Config,
    label: str,
    front_tenor: str,
    back_tenor: str,
    signal: pd.Series,
    grid_dates: Sequence[Any],
    *,
    show_progress: bool = False,
) -> Tuple[Any, List[Dict[str, Any]]]:
    """Wire one structure's overlapping cohorts into a ``QueryDrivenBacktest``.

    ``signal`` is a date-indexed series of {+1, 0, -1} for this structure, ALREADY
    LAGGED by the caller. Each non-zero cohort date opens two OUTRIGHT legs under
    its own tag (a shared tag would let one cohort's unwind close another's
    position, and unwinds process after fills) and schedules an unwind at the
    horizon. Cohorts whose horizon falls past the sample end get NO unwind
    trigger and stay marked to the end.

    Returns ``(bt, cohorts)`` where ``cohorts`` records each cohort's tag, entry,
    exit and direction so per-cohort P&L can be attributed after the run.
    """
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    if cfg.trade_straddle:
        # A knob that silently does nothing is worse than one that is missing.
        raise NotImplementedError(
            "trade_straddle=True is not wired into the engine. The note sizes the "
            "funding straddle so its premium intake equals the package's carry "
            "over the horizon, and that size was MEASURED here over 2019-2026: "
            "median $4.17 of underlying DV01 for 20Yx5Y/25Yx5Y (0.004% of a $100k "
            "package) against $17,169 for 5Y/30Y. For the forward structures the "
            "leg is a rounding error, so it was left out rather than wired in "
            "untested. Use straddle_dv01_for_carry() to size it, and note that "
            "JPM's Exhibit 5 hit rates DO include this leg while these do not.")

    grid = pd.DatetimeIndex([pd.Timestamp(d) for d in grid_dates]).sort_values()
    entries = [d for d in cohort_dates(grid, cfg.cohort_freq)
               if pd.Timestamp(d) in signal.index and float(signal.loc[pd.Timestamp(d)]) != 0.0]
    sched = cohort_schedule(grid, entries, cfg.horizon)

    triggers: List[Any] = []
    cohorts: List[Dict[str, Any]] = []
    for k, (entry, exit_) in enumerate(sched):
        s = float(signal.loc[pd.Timestamp(entry)])
        # +1 = cheap  -> FLATTENER (bpv<0): pay front, receive back
        # -1 = rich   -> STEEPENER (bpv>0): receive front, pay back
        front_bpv = +cfg.package_dv01 * s
        back_bpv = -cfg.package_dv01 * s
        tag = f"{label}_c{k:04d}"
        legs = [
            IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                        tenor=front_tenor, curve=cfg.curve,
                        structure_kwargs={"bpv": front_bpv}, tags=(tag,)),
            IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                        tenor=back_tenor, curve=cfg.curve,
                        structure_kwargs={"bpv": back_bpv}, tags=(tag,)),
        ]
        # DateTriggerRequirements tests ``state.date() in set(self.dates)``. A
        # pd.Timestamp in that set never compares equal to a datetime.date, so a
        # Timestamp here makes the trigger a SILENT no-op.
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[entry]),
            actions=[AddQueryAction(query=q, meta={"tags": [tag]}) for q in legs]))
        if exit_ is not None:
            fee = 2.0 * cfg.cost_bp_one_way * cfg.package_dv01
            triggers.append(DateTrigger(
                DateTriggerRequirements(dates=[exit_]),
                actions=[UnwindPositionsAction(match_tag=tag, fee=fee)]))
        cohorts.append({"tag": tag, "structure": label, "entry": pd.Timestamp(entry),
                        "exit": None if exit_ is None else pd.Timestamp(exit_),
                        "direction": s, "live_at_end": exit_ is None})

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(list(grid)),
        strategy=QueryStrategy(name=f"strat1_{label}", triggers=triggers),
        mdp=mdp,
        show_progress=show_progress,
    )
    return bt, cohorts


def cohort_table(bt: Any, cohorts: Sequence[Dict[str, Any]], cfg: Strat1Config) -> pd.DataFrame:
    """Per-cohort realised P&L from the engine's own closed-position log.

    Each cohort is two legs; the engine logs a closed position per leg with its
    own ``gross_realized_pnl`` and its share of the unwind fee, tagged with the
    cohort's tag in ``position_meta``. Summing by tag gives the cohort's round
    trip. Cohorts still LIVE at the sample end appear with NaN P&L and
    ``closed=False`` -- they are reported separately, never force-closed.
    """
    by_tag: Dict[str, Dict[str, float]] = {}
    for rec in (getattr(bt.portfolio, "closed_positions_log", []) or []):
        tags = list((rec.get("position_meta") or {}).get("tags", []) or [])
        if not tags:
            continue
        t = str(tags[0])
        d = by_tag.setdefault(t, {"gross": 0.0, "net": 0.0, "fee": 0.0, "legs": 0})
        d["gross"] += float(rec.get("gross_realized_pnl", 0.0))
        d["net"] += float(rec.get("realized_pnl", 0.0))
        d["fee"] += float(rec.get("fee_allocated", 0.0))
        d["legs"] += 1

    rows = []
    for c in cohorts:
        d = by_tag.get(c["tag"])
        rows.append({
            **c,
            "closed": d is not None,
            "n_legs_closed": 0 if d is None else int(d["legs"]),
            "gross_pnl_ccy": float("nan") if d is None else d["gross"],
            "net_pnl_ccy": float("nan") if d is None else d["net"],
            "fee_ccy": float("nan") if d is None else d["fee"],
            "gross_pnl_bp": float("nan") if d is None else d["gross"] / cfg.package_dv01,
            "net_pnl_bp": float("nan") if d is None else d["net"] / cfg.package_dv01,
        })
    return pd.DataFrame(rows)
