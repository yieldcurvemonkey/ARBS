"""Strategy 3 — delta-hedged long-dated forward flatteners ("strikeless vol").

Source: Citi *US Rates Vol Lab: Trading long-dated convexity* (Bikbov/Williams,
09-May-2019), plus the two 20y10y flattener alerts (16-Oct-2019 reweight,
05-Dec-2019 take-profit) and the GBP 15y10y/25y10y note (26-Mar-2020).

The trade, verbatim (Doc A, l.40-41)::

    "consider 10y10y/20y10y curve flatteners, structured by receiving 20y10y
     forward swaps vs paying 10y10y forward swaps, DV01-neutral."

Why it is long convexity (Doc A, l.44-46)::

    "Because convexity is higher at longer maturities, the 20y10y forward
     should have a greater convexity per a unit of DV01 than 10y10y. As a
     result, the 10y10y/20y10 flattener must be positively convex."

And how the convexity is monetised (Doc A, l.126-128)::

    "Although we initiate a DV01-neu[t]ral flattener, DV01 risks change as the
     market moves. We therefore delta-hedge the trade by adjusting the notional
     on the longer leg at each 25bp move in rates."

The PM's version of the same mechanic (``08-misc-notes-and-pm-chat.md`` §1)::

    "You just recalc the delta on the trades you do every 25 bp and then resize
     the notionals back to be dv01 neutral. Everytime you will be 'taking
     profit'. ... That's how you delta hedge and treat 10y10y 20y10y as a vol
     trade - I think of it as strikeless vol."

    "Depending on how you do the resize you can delta hedge it to 0 risk
     (always decrease) or keep it constant" -> ``Strat3Config.resize_mode``.

**The objective this module optimises.** Long gamma is table stakes; the thing
worth finding is a structure that is long gamma *and carries positively*. Every
screen row and every grid cell therefore reports CARRY next to Sharpe, and the
ledger keeps the carry bucket separate from the gamma-harvest bucket so a
positive total cannot hide a bleeding one.


What this module reuses, and what it adds
-----------------------------------------

``RVUtils.StrikelessVol`` already carries a tested aged-package pricer
(``replication.CurvePricer``), a delta-hedge simulator
(``replication.simulate``), package construction (``greeks.build_package``) and
a cost schedule. Those are reused unchanged — ``simulate_strat3`` is written
against the same ``PricingContext`` protocol and is asserted to reproduce
``replication.simulate`` exactly at ``beta=1.0, resize_mode="neutral"``
(``tests/test_convexity_rv_strat3.py``). What is new here:

* ``beta`` — Citi's one documented deviation from pure DV01-neutrality
  (Doc B, l.26-32: reweight 15y5y/20y10y with "the empirical beta of 1.025",
  raising the 20y10y notional from $81.97mn to $84mn).
* ``resize_mode="always_decrease"`` — the PM's self-liquidating variant.
* The full Citi 15-pair universe, the Figure-9 cost tiers, and the Figure-7
  entry screen with both breakeven calculations.


Two measurement findings that override the brief, both measured not assumed
---------------------------------------------------------------------------

**1. "1y carry" is the repriced 1-year roll of the aged package.** Citi never
states the formula (spec §13). Measured against Figure 7's eight published
carries on the close of 2019-05-08:

===============================================  ==========  =========
measure                                          corr        MAE (bp)
===============================================  ==========  =========
repriced 1y roll / package DV01 (this module)     **+0.991**  **0.35**
``CARRY_AND_ROLL_BPS_RUNNING``, horizon="1Y"      +0.991      0.34
``CARRY_AND_ROLL_BPS_RUNNING`` before 2026-08-27  -0.136      1.28
===============================================  ==========  =========

The third row is history, kept because several modules in this package were
written around it. The query value used to age a forward-starting leg by
shortening its TAIL rather than bringing its START nearer, so a 10Yx10Y aged
1Y became 10Yx9Y instead of 9Yx10Y; ``_query_carry_1y`` compounded it by
quoting the opposite trade direction. Both are fixed —
``Query.IRSwaps._carry_roll`` is now the single kernel behind both backends —
and the two carry paths agree to 0.02 bp of MAE. ``screen_frame`` still
reports both; ``carry_1y_bp`` (the repriced one) remains what every downstream
signal uses, now as a matter of provenance rather than of accuracy. See
``CARRY_TIEOUT_2019_05_08``.

**2. The exact breakeven cannot be taken from ``curve_ops.payoff_profile``.**
That function ages with ``rl.Curve.translate``, and translate returns *exactly*
zero carry for a par-struck, not-yet-started forward package — which is every
package here. Measured on 2019-05-08, USD 10y10y/20y10y, $100k DV01::

    horizon +1d :  translate  -0.00      roll    -350.68
    horizon +1y :  translate  +0.00      roll -129,434.37

(the same finding is pinned in ``StrikelessVol.greeks`` by
``test_translate_yields_no_carry_for_a_par_struck_forward_package``). So the
"exact" breakeven here is built from ``rl.Curve.roll`` for the carry and a
second-difference reprice for the gamma — still a full repricing, just not via
``translate``. ``payoff_profile`` remains correct and is used unchanged for the
shift-only convexity profile, where no ageing is involved.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field, replace
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "BUSINESS_DAYS",
    "CARRY_TIEOUT_2019_05_08",
    "CITI_FIG4_SHARPE",
    "CITI_FIG7_SCREEN",
    "FIG9_COST_BP",
    "PAIRS_15",
    "Strat3Config",
    "book_stats",
    "cost_schedule_for",
    "delta_m_years",
    "entry_state",
    "forward_pair",
    "grid_cells",
    "hedge_schedule",
    "leg_labels",
    "leg_metrics",
    "level_from_rates",
    "parse_fwd",
    "roll_segments",
    "run_grid",
    "screen_frame",
    "screen_panel_from_legs",
    "simulate_strat3",
    "stitch_segments",
    "unit_ledgers_for_pair",
]

#: Citi's Figure-4 Sharpe convention: annualised off DAILY P&L, 252 days.
#: Verified against the published table to 2dp for all eight columns
#: (e.g. 5.40/247.6*sqrt(252) = 0.346 -> 0.35).
BUSINESS_DAYS: float = 252.0

# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------

#: The 15-pair grid used by the Citi alerts and the cross-currency screens
#: (spec §1.4), written ``(short_leg, long_leg)`` with the repo's forward
#: notation ``"<start>x<tail>"``. The pair is always quoted shorter-dated leg
#: first; the trade PAYS the short leg and RECEIVES the long leg.
PAIRS_15: Tuple[Tuple[str, str], ...] = (
    ("10Yx10Y", "15Yx15Y"),
    ("10Yx10Y", "20Yx5Y"),
    ("10Yx10Y", "20Yx10Y"),
    ("10Yx10Y", "20Yx15Y"),
    ("10Yx10Y", "25Yx5Y"),
    ("10Yx10Y", "25Yx10Y"),
    ("15Yx5Y", "20Yx5Y"),
    ("15Yx5Y", "20Yx10Y"),
    ("15Yx5Y", "20Yx15Y"),
    ("15Yx5Y", "25Yx5Y"),
    ("15Yx5Y", "25Yx10Y"),
    ("15Yx10Y", "25Yx5Y"),
    ("15Yx10Y", "25Yx10Y"),
    ("20Yx5Y", "25Yx5Y"),
    ("20Yx5Y", "25Yx10Y"),
)

#: Doc A Figure 9, one-way bid/offer in bp of rate per $100K DV01:
#: ``pair -> (initiation, delta-hedge and roll)``. Only the eight Figure-4
#: pairs are published. ``10Yx5Y/15Yx15Y`` is in Figure 9 but not in the
#: 15-pair grid; it is kept so the Figure-9 table can be reproduced verbatim.
FIG9_COST_BP: Dict[Tuple[str, str], Tuple[float, float]] = {
    ("10Yx5Y", "15Yx15Y"): (0.75, 0.30),
    ("10Yx10Y", "15Yx15Y"): (0.75, 0.30),
    ("10Yx10Y", "20Yx10Y"): (0.75, 0.30),
    ("15Yx5Y", "20Yx10Y"): (0.75, 0.30),
    ("10Yx10Y", "20Yx15Y"): (1.00, 0.40),
    ("10Yx10Y", "25Yx10Y"): (1.00, 0.40),
    ("15Yx5Y", "20Yx15Y"): (1.00, 0.40),
    ("20Yx5Y", "25Yx10Y"): (1.00, 0.40),
}

#: Pairs outside Figure 9 default to the CONSERVATIVE (wider) tier. Recorded
#: as an assumption, not a measurement: Citi published eight quotes and the
#: 15-pair grid has seven more, all of them longer-dated or less standard than
#: the four tight ones, so the wide tier is the defensible default.
DEFAULT_COST_BP: Tuple[float, float] = (1.00, 0.40)

#: Doc A Figure 4, sample 12/31/2013-5/7/2019, $100K DV01, 25bp hedging, net of
#: Citi's own costs. The reference point every grid table is quoted against.
CITI_FIG4_SHARPE: Dict[Tuple[str, str], float] = {
    ("10Yx5Y", "15Yx15Y"): 0.05,
    ("10Yx10Y", "15Yx15Y"): 0.13,
    ("10Yx10Y", "20Yx10Y"): 0.16,
    ("10Yx10Y", "20Yx15Y"): 0.24,
    ("10Yx10Y", "25Yx10Y"): 0.35,
    ("15Yx5Y", "20Yx10Y"): 0.18,
    ("15Yx5Y", "20Yx15Y"): 0.25,
    ("20Yx5Y", "25Yx10Y"): 0.30,
}

#: Doc A Figure 4, the same table's mean and vol of daily P&L in $K.
CITI_FIG4_DAILY_K: Dict[Tuple[str, str], Tuple[float, float]] = {
    ("10Yx5Y", "15Yx15Y"): (0.67, 195.3),
    ("10Yx10Y", "15Yx15Y"): (1.15, 142.4),
    ("10Yx10Y", "20Yx10Y"): (2.28, 222.1),
    ("10Yx10Y", "20Yx15Y"): (3.20, 208.5),
    ("10Yx10Y", "25Yx10Y"): (5.40, 247.6),
    ("15Yx5Y", "20Yx10Y"): (2.92, 251.5),
    ("15Yx5Y", "20Yx15Y"): (3.79, 241.7),
    ("20Yx5Y", "25Yx10Y"): (4.09, 219.3),
}

#: Doc A Figure 7 — the entry screen at the close of 2019-05-08 (USD). The
#: external known-answer this module ties out against.
#: ``pair -> (curve_bp, zs_1y, zs_3y, carry_1y_bp, be_daily_bp, rlzd_vol_bp,
#: be_over_rv)``.
CITI_FIG7_SCREEN: Dict[Tuple[str, str], Tuple[float, float, float, float, float, float, float]] = {
    ("10Yx5Y", "15Yx15Y"): (-10.1, 2.50, 0.19, -2.91, 3.5, 3.2, 1.07),
    ("10Yx10Y", "15Yx15Y"): (-8.8, 2.15, 0.39, -1.64, 3.0, 3.2, 0.94),
    ("10Yx10Y", "20Yx10Y"): (-13.2, 1.87, 0.53, -1.75, 2.6, 3.1, 0.84),
    ("10Yx10Y", "20Yx15Y"): (-16.7, 2.41, 0.50, -1.88, 2.5, 3.1, 0.79),
    ("10Yx10Y", "25Yx10Y"): (-20.1, 2.38, 0.55, -1.83, 2.2, 3.0, 0.72),
    ("15Yx5Y", "20Yx10Y"): (-11.3, 1.16, 1.01, -0.31, 1.3, 3.0, 0.42),
    ("15Yx5Y", "20Yx15Y"): (-15.2, 1.62, 0.99, -0.44, 1.3, 3.0, 0.45),
    ("20Yx5Y", "25Yx10Y"): (-9.1, 1.95, 0.87, 0.13, 0.0, 3.0, 0.00),
}

#: Measured agreement of the candidate carry measures against Figure 7, close
#: of 2019-05-08, USD-SOFR-1D. Kept as a committed record so a later reader does
#: not have to re-derive it. (corr, mean-absolute-error in bp.)
#:
#: ``carry_and_roll_bps_running_pre_fix`` is the number this module was built
#: around: until 2026-08-27 the query value aged a forward-starting leg by
#: shortening its tail instead of bringing its start nearer, and
#: ``_query_carry_1y`` asked for the opposite trade direction on top. Both are
#: fixed (``Query.IRSwaps._carry_roll``), and the two paths now agree.
CARRY_TIEOUT_2019_05_08: Dict[str, Tuple[float, float]] = {
    "repriced_1y_roll": (0.991, 0.354),
    "carry_and_roll_bps_running": (0.991, 0.338),
    "carry_and_roll_bps_running_pre_fix": (-0.136, 1.278),
}


def parse_fwd(label: str) -> Tuple[float, float]:
    """``"20Yx10Y" -> (20.0, 10.0)``: (forward start, tail) in years."""
    a, b = str(label).upper().split("X")
    return float(a.rstrip("Y")), float(b.rstrip("Y"))


def leg_labels(pairs: Iterable[Tuple[str, str]] = PAIRS_15) -> List[str]:
    """Every distinct forward leg the universe needs, once.

    Nine legs cover all fifteen pairs. Pricing per LEG rather than per PAIR is
    what makes a daily 15-pair screen affordable: package DV01, gamma and roll
    are all exactly linear in the two legs' notionals, so the pair-level
    numbers are a two-term combination of cached per-leg unit quantities.
    """
    seen: List[str] = []
    for s, l in pairs:
        for lab in (s, l):
            if lab not in seen:
                seen.append(lab)
    return seen


def forward_pair(short: str, long: str, *, market: str = "USD",
                 curve_name: str = "USD-SOFR-1D"):
    """A ``StrikelessVol.universe.ForwardPair`` from two ``"AYxBY"`` labels."""
    from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

    sf, st = parse_fwd(short)
    lf, lt = parse_fwd(long)
    return ForwardPair(
        market=market,
        curve_name=curve_name,
        short=ForwardLeg(f"{sf:g}Y", f"{st:g}Y"),
        long=ForwardLeg(f"{lf:g}Y", f"{lt:g}Y"),
    )


def delta_m_years(short: str, long: str) -> float:
    """``dM = M_long - M_short``, ``M = forward_start + tail/2``.

    The spec's reconstruction of Citi's implied convexity (§3.3/§11.2): the net
    convexity of a DV01-neutral flattener is ``Gamma = dM/10000`` bp of curve
    P&L per bp squared of parallel shift, per unit of trade DV01. Verified two
    independent ways — inverted from Citi's own published carry/breakeven pairs
    across four publication dates and five currencies (mean |error| ~2%), and
    directly against a second-difference reprice here (see
    ``screen_frame``'s ``gamma_ratio_vs_theory`` column, ~2.5% on 2019-05-08).
    """
    sf, st = parse_fwd(short)
    lf, lt = parse_fwd(long)
    return (lf + lt / 2.0) - (sf + st / 2.0)


def cost_schedule_for(short: str, long: str, *, multiplier: float = 1.0):
    """Citi Figure-9 ``CostSchedule`` for a pair; wide tier if unpublished."""
    from RVUtils.StrikelessVol.costs import CostSchedule

    init_bp, hedge_bp = FIG9_COST_BP.get((short, long), DEFAULT_COST_BP)
    return CostSchedule(initiate_bp=init_bp, hedge_bp=hedge_bp, roll_bp=hedge_bp,
                        multiplier=float(multiplier))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Strat3Config:
    """Every knob of the strategy, documented inline.

    Defaults reproduce Citi's Figure-4 backtest specification: $100K DV01,
    DV01-neutral at initiation, delta-hedged at each 25bp move in the LONGER
    forward rate observed at close, rolled every year, charged at the Figure-9
    schedule.
    """

    # --- WHAT IS TRADED ---------------------------------------------------
    short_leg: str = "15Yx5Y"          # paid  (shorter-dated forward)
    long_leg: str = "20Yx10Y"          # received (longer-dated forward)
    curve_name: str = "USD-SOFR-1D"
    market: str = "USD"
    package_dv01_usd: float = 100_000.0  # Citi Fig-4 size; the alerts used $50K

    # --- THE DELTA HEDGE --------------------------------------------------
    #: Move in the LONGER forward rate, at close, that triggers a resize.
    #: Doc A l.129-139: "chosen as a trade-off between the accuracy of hedging
    #: and transaction costs ... the Sharpe ratio doesn't change significantly
    #: if the threshold is chosen in the 15-30bp range, but declines with a
    #: smaller or larger threshold."
    hedge_threshold_bp: float = 25.0
    #: Multiplier on the DV01-neutral target notional of the LONGER leg.
    #: 1.0 = pure DV01-neutral. Doc B used 1.025 ("the empirical beta of 1.025
    #: between 15y5y and 20y10y rates ... scaling the DV01-neutral notional up
    #: by 1.025") after the curve turned directional.
    beta: float = 1.0
    #: "neutral"          — resize to the DV01-neutral target every time.
    #: "always_decrease"  — resize only when it SHRINKS the longer leg, so the
    #:                      book self-liquidates and the hedge becomes the exit
    #:                      (the PM's second variant).
    resize_mode: str = "neutral"
    #: Months between rolls. The package is rebuilt at market on the roll date.
    roll_months: int = 12

    # --- COSTS ------------------------------------------------------------
    #: Scales the Figure-9 schedule. 0 = gross, 1 = Citi's assumption, 2 = a
    #: capacity stress. Never quote a number at one multiplier only.
    cost_multiplier: float = 1.0

    # --- ENTRY GATE (all gates are evaluated LAG-1) -----------------------
    #: "always"   — always on, Citi's own Figure-4 specification.
    #: "z"        — on when the level z-score >= ``z_min`` (steep = attractive
    #:              flattener entry, Doc A §8.1).
    #: "be_ratio" — on when daily-BE / 1y-realized-vol <= ``be_ratio_max``
    #:              (Doc C: entry at 0.42-0.45, exit flagged at 0.80).
    #: "z_and_be" — both.
    #: "carry"    — on when 1y carry >= ``carry_min_bp`` (the "free convexity
    #:              buy" filter: long gamma AND paid to hold it).
    entry_rule: str = "always"
    z_window: str = "3y"               # "1y" | "3y" | "full"
    z_min: float = 1.0
    be_ratio_max: float = 0.80
    carry_min_bp: float = 0.0

    # --- SAMPLE -----------------------------------------------------------
    start: dt.date = dt.date(2019, 1, 1)
    end: dt.date = dt.date(2026, 8, 14)
    #: Extra history loaded ONLY to seed the z-score and realized-vol windows.
    #: No P&L is earned here.
    warmup_start: dt.date = dt.date(2013, 1, 1)

    @property
    def pair(self) -> Tuple[str, str]:
        return (self.short_leg, self.long_leg)

    @property
    def pair_name(self) -> str:
        return f"{self.short_leg}/{self.long_leg}"

    def with_(self, **kw) -> "Strat3Config":
        return replace(self, **kw)

    def to_dict(self) -> dict:
        return {k: (str(v) if isinstance(v, dt.date) else v) for k, v in asdict(self).items()}


# ---------------------------------------------------------------------------
# Per-leg repriced metrics — the screen's engine
# ---------------------------------------------------------------------------


def leg_metrics(pricer, label: str, *, h_dv01_bp: float = 1.0,
                h_gamma_bp: float = 25.0,
                roll_horizons: Sequence[Tuple[str, object]] = ()) -> Dict[str, float]:
    """Unit-notional repriced metrics for one forward leg on one curve.

    Everything is per **+1 notional of a PAYER swap struck at market today**,
    so a package is a two-term linear combination:

    ``n_short = +DV01 / dv01_short``  (pay the shorter leg)
    ``n_long  = -DV01 / dv01_long``   (receive the longer leg)

    and then ``package_X = n_short * X_short + n_long * X_long`` for
    ``X in {dv01, gamma, roll}``, exactly — rateslib's NPV is linear in
    notional. ``package_dv01`` is identically zero by construction, which is
    tie-out (b).

    ``dv01`` is a central difference on a +/-1bp parallel curve shift, matching
    ``StrikelessVol.greeks._reprice_dv01`` — deliberately NOT ``curve.pv01``
    (the analytic annuity), which diverges from the repriced measure by up to
    10% on an inverted long end. Sizing on one and checking neutrality on the
    other is how a directional residual gets into a package whose whole premise
    is that it has none.
    """
    fwd, tail = parse_fwd(label)
    swap = pricer.build_irswap(fwd=f"{fwd:g}Y", tenor=f"{tail:g}Y", notional=1.0)
    handle = pricer.handle()

    def npv(h) -> float:
        return float(swap.npv(curves=h).real)

    base = npv(handle)
    up1, dn1 = npv(handle.shift(h_dv01_bp)), npv(handle.shift(-h_dv01_bp))
    upg, dng = npv(handle.shift(h_gamma_bp)), npv(handle.shift(-h_gamma_bp))
    out = {
        "rate_bp": float(pricer.fair_rate(swap)) * 1e4,
        "npv": base,
        "dv01": (up1 - dn1) / (2.0 * h_dv01_bp),
        "gamma": (upg + dng - 2.0 * base) / (h_gamma_bp ** 2),
    }
    for name, horizon in roll_horizons:
        out[f"roll_{name}"] = npv(handle.roll(pd.Timestamp(horizon).to_pydatetime())) - base
    return out


def level_from_rates(rates: pd.DataFrame, short: str, long: str) -> pd.Series:
    """Curve level in bp, Citi's sign: ``rate(long) - rate(short)``.

    Normally negative — the ultra-long forward curve is inverted (Doc A Fig 1).
    A HIGHER (less negative) level is a steeper curve and a more attractive
    flattener entry, which is why the z-score's polarity is "high = attractive".
    """
    return rates[long] - rates[short]


def screen_frame(
    pricer,
    pairs: Sequence[Tuple[str, str]] = PAIRS_15,
    *,
    asof: Optional[dt.date] = None,
    package_dv01_usd: float = 100_000.0,
    level_hist: Optional[pd.DataFrame] = None,
    rate_hist: Optional[pd.DataFrame] = None,
    business_days: float = BUSINESS_DAYS,
    include_query_carry: bool = False,
    curve_name: str = "USD-SOFR-1D",
) -> pd.DataFrame:
    """The Citi Figure-7 entry screen, one row per pair, on one curve.

    Columns
    -------
    ``level_bp``            ``rate(long) - rate(short)``, bp.
    ``zs_1y``/``zs_3y``/``zs_full``
                            z-scores of ``level_bp`` on the trailing window,
                            from ``level_hist`` (inclusive of ``asof``).
    ``carry_1y_bp``         the repriced 1-year roll of the DV01-neutral aged
                            package divided by package DV01 — Citi's "1y
                            carry, bp" (see the module docstring's tie-out).
    ``carry_query_bp``      ``IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING`` at
                            horizon 1Y, same trade direction as
                            ``carry_1y_bp``. An independent second path, kept
                            as a cross-check: the two agree to 0.02 bp of MAE
                            against Figure 7.
    ``gamma_usd_bp2``       repriced ``d2PV/dshift2`` of the package, $/bp^2.
    ``gamma_theory_usd``    ``2 * (dM/1e4) * DV01`` — the spec's reconstruction.
    ``gamma_ratio``         repriced / theory. ~1.00 validates the ``dM/1e4``
                            reconstruction independently of Citi's tables.
    ``be_daily_analytic``   ``sqrt(|carry| / (252 * dM/1e4))``, 0 if carry >= 0
                            — the published formula, reconstructed in the spec.
    ``be_daily_exact``      the same quantity computed entirely by repricing:
                            ``sqrt(2 * |roll_1y/252| / gamma_repriced)``.
    ``be_agreement``        exact / analytic. Reports how much of the published
                            breakeven survives dropping the reconstruction.
    ``rlzd_vol_bp``         trailing 1y std of DAILY changes in the LONGER
                            forward rate, bp/day (Doc A Fig 3's own ruler:
                            "1y realized vol of 20y10y"; every published table
                            shows this row identical for all pairs sharing a
                            long leg, which is how the convention was pinned).
    ``be_over_rv``          the decision statistic. Lower = the embedded
                            convexity is cheaper = more attractive flattener.
    """
    asof = asof or _as_date(pricer.reference_date())
    ts = pd.Timestamp(asof)
    horizons = (("1y", ts + pd.DateOffset(years=1)), ("1d", ts + pd.Timedelta(days=1)))
    legs = {lab: leg_metrics(pricer, lab, roll_horizons=horizons)
            for lab in leg_labels(pairs)}

    rows = []
    for short, long in pairs:
        s, l = legs[short], legs[long]
        n_short = +package_dv01_usd / s["dv01"]
        n_long = -package_dv01_usd / l["dv01"]
        pkg_dv01 = n_short * s["dv01"] + n_long * l["dv01"]
        gamma = n_short * s["gamma"] + n_long * l["gamma"]
        roll_1y = n_short * s["roll_1y"] + n_long * l["roll_1y"]
        roll_1d = n_short * s["roll_1d"] + n_long * l["roll_1d"]
        carry_bp = roll_1y / package_dv01_usd
        dM = delta_m_years(short, long)
        gamma_theory = 2.0 * (dM / 1e4) * package_dv01_usd

        if carry_bp >= 0:
            be_an = 0.0
            be_ex = 0.0
        else:
            be_an = math.sqrt(abs(carry_bp) / (business_days * dM / 1e4))
            be_ex = (math.sqrt(2.0 * abs(roll_1y / business_days) / gamma)
                     if gamma > 0 else float("nan"))

        rec = {
            "pair": f"{short}/{long}",
            "short_leg": short,
            "long_leg": long,
            "date": ts,
            "short_rate_bp": s["rate_bp"],
            "long_rate_bp": l["rate_bp"],
            "level_bp": l["rate_bp"] - s["rate_bp"],
            "package_dv01_usd": pkg_dv01,
            "carry_1y_bp": carry_bp,
            "roll_1d_usd": roll_1d,
            "dM_years": dM,
            "gamma_usd_bp2": gamma,
            "gamma_theory_usd": gamma_theory,
            "gamma_ratio": gamma / gamma_theory if gamma_theory else np.nan,
            "be_daily_analytic": be_an,
            "be_daily_exact": be_ex,
            "be_agreement": (be_ex / be_an) if be_an else np.nan,
            "n_short": n_short,
            "n_long": n_long,
        }
        if include_query_carry:
            rec["carry_query_bp"] = _query_carry_1y(pricer, short, long, curve_name,
                                                    package_dv01_usd)
        rows.append(rec)

    out = pd.DataFrame(rows)

    # z-scores of the level and realized vol of the LONGER rate
    for w in ("1y", "3y", "full"):
        out[f"zs_{w}"] = np.nan
    out["rlzd_vol_bp"] = np.nan
    if level_hist is not None and len(level_hist):
        hist = level_hist[level_hist.index <= ts]
        for i, r in out.iterrows():
            col = r["pair"]
            if col not in hist.columns:
                continue
            ser = hist[col].dropna()
            for w, n in (("1y", 252), ("3y", 756), ("full", None)):
                x = ser if n is None else ser.iloc[-n:]
                if len(x) > 20 and x.std(ddof=1) > 0:
                    out.at[i, f"zs_{w}"] = float((x.iloc[-1] - x.mean()) / x.std(ddof=1))
    if rate_hist is not None and len(rate_hist):
        rh = rate_hist[rate_hist.index <= ts]
        for i, r in out.iterrows():
            col = r["long_leg"]
            if col not in rh.columns:
                continue
            d = rh[col].diff().dropna().iloc[-252:]
            if len(d) > 20:
                out.at[i, "rlzd_vol_bp"] = float(d.std(ddof=1))

    out["be_over_rv"] = out["be_daily_analytic"] / out["rlzd_vol_bp"]
    out["be_over_rv_exact"] = out["be_daily_exact"] / out["rlzd_vol_bp"]
    return out


def _query_carry_1y(pricer, short: str, long: str, curve_name: str,
                    package_dv01_usd: float) -> float:
    """``CARRY_AND_ROLL_BPS_RUNNING`` at 1Y on the CURVE package, bpv>0.

    ``bpv > 0`` constrains the BACK leg positive, so ``_build_curve`` returns
    weights ``(-1 front, +1 back)`` — pay the short leg, receive the long leg,
    which is the trade Citi's Figure-7 carry column is quoted for. This used to
    pass ``bpv < 0``, i.e. the opposite trade, so the comparison it fed was
    sign-flipped on top of the ageing bug the query value itself carried.

    With both fixed the two carry paths agree: measured 2019-05-08 on the eight
    Figure-7 pairs, corr **+0.991** / MAE **0.338 bp** against the published
    carries, versus +0.991 / 0.354 for the repriced roll. See the module
    docstring and ``CARRY_TIEOUT_2019_05_08``.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    q = IRSwapQuery(structure=IRSwapStructure.CURVE, value=IRSwapValue.RATE,
                    curve=curve_name,
                    structure_kwargs={"front_tenor": short, "back_tenor": long,
                                      "bpv": abs(package_dv01_usd)})
    pkg, w = q.resolve_package(pricer_or_curve=pricer)
    pkg = [pricer.resolve_pricable(p, rw) for p, rw in zip(pkg, w)]
    vmap = q.build_value_map(pricer_or_curve=pricer, package=pkg, risk_weights=w)
    return float(vmap.apply(value=IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING, horizon="1Y"))


def screen_panel_from_legs(leg_panel: pd.DataFrame,
                           pairs: Sequence[Tuple[str, str]] = PAIRS_15,
                           *, package_dv01_usd: float = 100_000.0,
                           business_days: float = BUSINESS_DAYS) -> pd.DataFrame:
    """Vectorised daily screen from a long-format per-leg metrics panel.

    ``leg_panel`` is indexed ``(date, leg)`` with columns ``rate_bp, dv01,
    gamma, roll_1y, roll_1d`` — one ``leg_metrics`` call per leg per day. The
    pair-level algebra is the same two-term linear combination as
    ``screen_frame``, done here on whole columns so a 1900-day, 15-pair screen
    costs nine repricing passes a day rather than thirty.
    """
    frames = []
    for short, long in pairs:
        try:
            s = leg_panel.xs(short, level="leg")
            l = leg_panel.xs(long, level="leg")
        except KeyError:
            continue
        idx = s.index.intersection(l.index)
        s, l = s.loc[idx], l.loc[idx]
        n_short = package_dv01_usd / s["dv01"]
        n_long = -package_dv01_usd / l["dv01"]
        gamma = n_short * s["gamma"] + n_long * l["gamma"]
        roll_1y = n_short * s["roll_1y"] + n_long * l["roll_1y"]
        carry_bp = roll_1y / package_dv01_usd
        dM = delta_m_years(short, long)
        neg = (carry_bp < 0).to_numpy()
        be_an = np.where(neg, np.sqrt(np.abs(np.minimum(carry_bp.to_numpy(), 0.0))
                                      / (business_days * dM / 1e4)), 0.0)
        g = gamma.to_numpy()
        safe_g = np.where(g > 0, g, np.nan)
        be_ex = np.where(neg & (g > 0),
                         np.sqrt(2.0 * np.abs(roll_1y.to_numpy() / business_days) / safe_g),
                         0.0)
        frames.append(pd.DataFrame({
            "pair": f"{short}/{long}",
            "short_leg": short,
            "long_leg": long,
            "short_rate_bp": s["rate_bp"],
            "long_rate_bp": l["rate_bp"],
            "level_bp": l["rate_bp"] - s["rate_bp"],
            "carry_1y_bp": carry_bp,
            "gamma_usd_bp2": gamma,
            "gamma_theory_usd": 2.0 * (dM / 1e4) * package_dv01_usd,
            "dM_years": dM,
            "be_daily_analytic": be_an,
            "be_daily_exact": be_ex,
        }, index=idx))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames)
    out.index.name = "date"
    out["gamma_ratio"] = out["gamma_usd_bp2"] / out["gamma_theory_usd"]
    return out.reset_index().set_index(["date", "pair"]).sort_index()


def add_screen_stats(panel: pd.DataFrame, leg_panel: pd.DataFrame,
                     *, z_windows=(("1y", 252), ("3y", 756), ("full", None)),
                     vol_window: int = 252) -> pd.DataFrame:
    """Attach rolling z-scores of the level and realized vol of the long leg."""
    out = panel.copy()
    lvl = out["level_bp"].unstack("pair").sort_index()
    for name, n in z_windows:
        if n is None:
            mu = lvl.expanding(min_periods=60).mean()
            sd = lvl.expanding(min_periods=60).std(ddof=1)
        else:
            mu = lvl.rolling(n, min_periods=max(60, n // 4)).mean()
            sd = lvl.rolling(n, min_periods=max(60, n // 4)).std(ddof=1)
        z = ((lvl - mu) / sd).stack().rename(f"zs_{name}")
        out = out.join(z, how="left")
    rates = leg_panel["rate_bp"].unstack("leg").sort_index()
    rv = rates.diff().rolling(vol_window, min_periods=120).std(ddof=1)
    rv_long = out.reset_index().apply(
        lambda r: rv.at[r["date"], r["long_leg"]] if (r["date"] in rv.index
                                                      and r["long_leg"] in rv.columns) else np.nan,
        axis=1)
    out["rlzd_vol_bp"] = rv_long.to_numpy()
    out["be_over_rv"] = out["be_daily_analytic"] / out["rlzd_vol_bp"]
    return out


# ---------------------------------------------------------------------------
# The delta-hedge engine
# ---------------------------------------------------------------------------

RESIZE_MODES = ("neutral", "always_decrease")


def simulate_strat3(ctx, dates: Sequence, cfg: Strat3Config, costs) -> pd.DataFrame:
    """Run the delta-hedge rule down one aged package's path.

    This is ``StrikelessVol.replication.simulate`` with two knobs added, and it
    is asserted to reproduce that function bit-for-bit at ``beta=1.0,
    resize_mode="neutral"`` (``test_engine_matches_strikeless_vol_simulate``).
    The upstream function is deliberately not modified: the ``sv_*`` scripts and
    their pinned tests depend on its exact behaviour.

    Mechanics, per Citi::

        "We delta-hedge by adjusting the notional on the longer end of the
         trade at each 25bp move in the longer rate (at market close)."

    * Initiation sizes both legs to ``package_dv01_usd`` off their own repriced
      DV01, then scales the longer leg by ``beta``.
    * At each ``hedge_threshold_bp`` move in the LONGER forward rate — measured
      on the constant-maturity rate, not the ageing leg's own fair rate, so the
      trigger tracks the market rather than the position's birthday — the
      longer leg is resized to ``beta * (-n_short * dv01_short / dv01_long)``.
      Targeting NEUTRALITY against the shorter leg as held (rather than a fixed
      $ DV01) matters once the package ages, because the shorter leg is never
      resized and its own repriced DV01 drifts too.
    * ``resize_mode="always_decrease"`` skips any resize that would GROW the
      longer leg, so the book winds down and the hedge doubles as the exit.

    The ledger keeps five buckets. ``carry`` is the day's repriced roll,
    ``harvest`` is the full repriced P&L of the resize increments (this is the
    gamma the strategy scalps), ``mtm`` is the curve move on the base notionals
    net of their carry, ``cross`` is an arithmetic check that is identically
    zero by construction, and ``cost`` is the fee. Traded RISK is recorded in
    separate columns so the same path can be repriced at another cost schedule
    without re-running it.
    """
    if cfg.resize_mode not in RESIZE_MODES:
        raise ValueError(f"resize_mode must be one of {RESIZE_MODES}, got {cfg.resize_mode!r}")
    dates = list(dates)
    if not dates:
        return pd.DataFrame()

    beta = float(cfg.beta)
    sign = +1  # FLATTENER
    dv01_pkg = float(cfg.package_dv01_usd)

    d0 = dates[0]
    n_long = beta * sign * dv01_pkg / ctx.dv01(d0, "long")
    n_short = -sign * dv01_pkg / ctx.dv01(d0, "short")

    last_hedge_rate_bp = ctx.rate(d0, "long") * 1e4
    inception = pd.Timestamp(d0)

    n_long_base = n_long
    prev_pv = ctx.pv(d0, n_long, n_short)
    prev_base_pv = prev_pv
    rows = [{
        "date": pd.Timestamp(d0),
        "carry": 0.0, "harvest": 0.0, "mtm": 0.0, "cross": 0.0,
        "cost": -costs.cost_usd("initiate", abs(dv01_pkg)),
        "initiate_dv01_usd": abs(dv01_pkg),
        "hedge_dv01_usd": 0.0,
        "roll_dv01_usd": 0.0,
        "n_hedges": 0, "n_rolls": 0,
        "long_notional": n_long, "short_notional": n_short,
        # TRUE package delta, dollars per bp. ``ctx.dv01`` is the NEGATED
        # per-unit measure (see CurvePricer.dv01's docstring: the negation is
        # what makes ``sign=+1`` receive the longer leg), so the position's own
        # dollars-per-bp is minus that combination. Zero at inception when
        # beta == 1 -- tie-out (b) -- and non-zero once the market has moved,
        # which is the delta the hedge exists to remove -- tie-out (e).
        "package_dv01_usd": -(n_long * ctx.dv01(d0, "long")
                              + n_short * ctx.dv01(d0, "short")),
        "position_age_years": 0.0,
    }]

    for d in dates[1:]:
        long_rate_bp = ctx.rate(d, "long") * 1e4

        full_pv_today = ctx.pv(d, n_long, n_short)
        total_pv_change = full_pv_today - prev_pv
        carry = float(ctx.theta(d, n_long, n_short))
        base_pv = ctx.pv(d, n_long_base, n_short)
        base_carry = float(ctx.theta(d, n_long_base, n_short))
        mtm = (base_pv - prev_base_pv) - base_carry
        increment_pv_today = full_pv_today - base_pv
        increment_pv_yesterday = prev_pv - prev_base_pv
        increment_carry = carry - base_carry
        harvest = (increment_pv_today - increment_pv_yesterday) - increment_carry
        cross = total_pv_change - (carry + mtm + harvest)

        cost = 0.0
        n_hedges = 0
        hedge_dv01 = 0.0

        # 1e-6 bp tolerance closes the decimal->bp float round trip only; a
        # genuine 25bp move can land at 24.999999999999943 purely from that.
        if abs(long_rate_bp - last_hedge_rate_bp) >= cfg.hedge_threshold_bp - 1e-6:
            target_long = beta * (-n_short * ctx.dv01(d, "short") / ctx.dv01(d, "long"))
            if cfg.resize_mode == "always_decrease" and abs(target_long) >= abs(n_long):
                target_long = n_long
            delta_n = target_long - n_long
            if delta_n != 0.0:
                n_long = target_long
                hedge_dv01 = abs(delta_n * ctx.dv01(d, "long"))
                cost -= costs.cost_usd("hedge", hedge_dv01)
                n_hedges = 1
            last_hedge_rate_bp = long_rate_bp

        rows.append({
            "date": pd.Timestamp(d),
            "carry": carry, "harvest": harvest, "mtm": mtm, "cross": cross,
            "cost": cost,
            "initiate_dv01_usd": 0.0,
            "hedge_dv01_usd": hedge_dv01,
            "roll_dv01_usd": 0.0,
            "n_hedges": n_hedges, "n_rolls": 0,
            "long_notional": n_long, "short_notional": n_short,
            "package_dv01_usd": -(n_long * ctx.dv01(d, "long")
                                  + n_short * ctx.dv01(d, "short")),
            "position_age_years": (pd.Timestamp(d) - inception).days / 365.0,
        })
        prev_pv = ctx.pv(d, n_long, n_short)
        prev_base_pv = ctx.pv(d, n_long_base, n_short)

    led = pd.DataFrame(rows).set_index("date")
    led["total"] = led[["carry", "harvest", "mtm", "cross", "cost"]].sum(axis=1)
    return led


def roll_segments(dates: Sequence, roll_months: int = 12) -> List[Tuple[int, int]]:
    """Inclusive index ranges of the roll periods, overlapping by one date.

    Segment ``k`` ends on the same date segment ``k+1`` starts: that date is
    the roll, the old package is held through it (its P&L belongs to ``k``) and
    the new one is struck on its curve (it prices from ``k+1``'s second row on).
    Without the overlap the roll date would earn nothing at all.

    The roll lives here, outside the simulator, because ``CurvePricer`` holds
    ONE aged package by contract — a roll is a genuinely new package built on
    the roll date's curve, not a notional reset on the old one.
    """
    dates = list(dates)
    if len(dates) < 2:
        return [(0, len(dates) - 1)] if dates else []
    bounds: List[Tuple[int, int]] = []
    i, last = 0, len(dates) - 1
    while i < last:
        due = pd.Timestamp(dates[i]) + pd.DateOffset(months=roll_months)
        j = i + 1
        while j < last and pd.Timestamp(dates[j]) < due:
            j += 1
        bounds.append((i, j))
        i = j
    return bounds


_FLOW_COLS = ["carry", "harvest", "mtm", "cross", "cost"]
_VOL_COLS = ["initiate_dv01_usd", "hedge_dv01_usd", "roll_dv01_usd", "n_hedges", "n_rolls"]


def stitch_segments(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate segment ledgers, summing flows on the shared roll dates.

    The roll is re-labelled here: only the FIRST segment's opening trade is an
    initiation; every later segment's opening trade is a roll, and Citi charges
    the roll at the hedge rate ("We assume the same bid/offer for the roll as
    for delta-hedging", Doc A l.155). Keeping the volume columns separate from
    the fee is what lets a caller re-price the whole path at another schedule.
    """
    frames = [f for f in frames if f is not None and len(f)]
    if not frames:
        return pd.DataFrame()
    relabelled = []
    for k, f in enumerate(frames):
        g = f.copy()
        if k > 0:
            first = g.index[0]
            g.loc[first, "roll_dv01_usd"] = g.loc[first, "initiate_dv01_usd"]
            g.loc[first, "initiate_dv01_usd"] = 0.0
            g.loc[first, "n_rolls"] = 1
        relabelled.append(g)
    stacked = pd.concat(relabelled)
    flows = stacked.groupby(level=0)[_FLOW_COLS + _VOL_COLS].sum()
    state = stacked.groupby(level=0)[["long_notional", "short_notional",
                                      "package_dv01_usd", "position_age_years"]].last()
    out = flows.join(state).sort_index()
    out["total"] = out[_FLOW_COLS].sum(axis=1)
    return out


def recost(ledger: pd.DataFrame, costs) -> pd.Series:
    """Re-charge a ledger's recorded traded RISK at another cost schedule.

    Vectorised on the linear branch (``clip_exponent == 0``, the only schedule
    used here): the grid scores ~15,000 cells off ~2,000-day ledgers, and a
    per-element ``cost_usd`` call would be ~90 million Python calls.
    """
    fee = pd.Series(0.0, index=ledger.index)
    rates = {"initiate_dv01_usd": costs.initiate_bp, "hedge_dv01_usd": costs.hedge_bp,
             "roll_dv01_usd": costs.roll_bp}
    kinds = {"initiate_dv01_usd": "initiate", "hedge_dv01_usd": "hedge",
             "roll_dv01_usd": "roll"}
    for col, rate in rates.items():
        if col not in ledger.columns:
            continue
        vol = ledger[col].abs().fillna(0.0)
        if getattr(costs, "clip_exponent", 0.0):
            fee = fee + vol.map(lambda v, k=kinds[col]: costs.cost_usd(k, v))
        else:
            fee = fee + costs.multiplier * rate * vol
    return fee


# ---------------------------------------------------------------------------
# Entry gates and book statistics
# ---------------------------------------------------------------------------


def entry_state(screen: pd.DataFrame, cfg: Strat3Config, index: pd.Index) -> pd.Series:
    """A LAG-1 {0,1} occupancy state for one pair, on the ledger's own dates.

    ``screen`` is the constant-maturity daily screen for this pair (one row per
    date). Lagging by one day is not decoration: the screen is computed at the
    close, so a same-day state would trade on information the close produced.
    """
    if cfg.entry_rule == "always":
        return pd.Series(1.0, index=index)
    s = screen.sort_index()
    z = s.get(f"zs_{cfg.z_window}")
    if cfg.entry_rule == "z":
        on = (z >= cfg.z_min)
    elif cfg.entry_rule == "be_ratio":
        on = (s["be_over_rv"] <= cfg.be_ratio_max)
    elif cfg.entry_rule == "z_and_be":
        on = (z >= cfg.z_min) & (s["be_over_rv"] <= cfg.be_ratio_max)
    elif cfg.entry_rule == "carry":
        on = (s["carry_1y_bp"] >= cfg.carry_min_bp)
    else:
        raise ValueError(f"unknown entry_rule {cfg.entry_rule!r}")
    return (on.astype(float).shift(1).fillna(0.0)
            .reindex(index).ffill().fillna(0.0))


def book_stats(ledger: pd.DataFrame, state: Optional[pd.Series] = None,
               *, costs=None, span_years: Optional[float] = None,
               package_dv01_usd: float = 100_000.0) -> dict:
    """Daily-MTM statistics for a (possibly gated) book, in dollars.

    Sharpe is Citi's Figure-4 convention: ``mean(daily $) / std(daily $) *
    sqrt(252)``, on EVERY day in the sample including flat ones — that is what
    makes a gated book comparable to an always-on one and what makes the number
    comparable to Citi's published 0.05..0.35.

    A gated book scales the always-on aged ledger's daily flows by a {0,1}
    state rather than striking a fresh package at each entry. That is the same
    approximation ``scripts/sv_citivelo_h13.py`` documents: the position is an
    aged package, the signal is a market property. Entry/exit are charged at
    the initiation rate on each flip, and an episode still open at the end of
    the sample is charged a synthetic terminal exit so an unclosed leg cannot
    flatter the book.
    """
    idx = ledger.index
    s = pd.Series(1.0, index=idx) if state is None else state.reindex(idx).fillna(0.0)
    gross = ledger[["carry", "harvest", "mtm", "cross"]].sum(axis=1) * s
    carry = ledger["carry"] * s
    harvest = ledger["harvest"] * s
    mtm = ledger["mtm"] * s

    fee = (-ledger["cost"] if costs is None else recost(ledger, costs)) * s
    # Gate fees are charged ONLY for a gated book. An always-on book's own
    # opening trade is already in the ledger's ``initiate_dv01_usd`` column, so
    # charging a flip on day one as well would double-bill the initiation.
    gate_fee = pd.Series(0.0, index=idx)
    if state is not None and costs is not None and len(s):
        flips = s.diff().fillna(s.iloc[0])
        gate_fee = flips.abs() * costs.cost_usd("initiate", abs(package_dv01_usd))
        if s.iloc[-1] > 0:
            # an episode still open at the end of the sample is charged a
            # synthetic terminal exit, so an unclosed leg cannot flatter the book
            gate_fee.iloc[-1] += costs.cost_usd("initiate", abs(package_dv01_usd))
    net = gross - fee - gate_fee

    # The directional line, removed. ``mtm`` is what the SAME aged package
    # would have earned with nobody hedging it -- the curve move on the base
    # notionals, net of their carry. So ``carry + harvest - costs`` is the book
    # with the direction stripped out: the roll it paid to exist plus the money
    # the resizes actually booked. Over a sample in which the long-end forward
    # curve inverted by ~45bp, that distinction is the whole difference between
    # "the delta hedge worked" and "the curve went the right way".
    net_ex_mtm = carry + harvest - fee - gate_fee

    n = len(net)
    sd = float(net.std(ddof=1)) if n > 2 else np.nan
    mu = float(net.mean()) if n else np.nan
    sharpe = (mu / sd * math.sqrt(BUSINESS_DAYS)) if sd and np.isfinite(sd) and sd > 0 else np.nan
    sd_x = float(net_ex_mtm.std(ddof=1)) if n > 2 else np.nan
    sharpe_ex_mtm = ((float(net_ex_mtm.mean()) / sd_x * math.sqrt(BUSINESS_DAYS))
                     if sd_x and np.isfinite(sd_x) and sd_x > 0 else np.nan)
    eq = net.cumsum()
    dd = eq - eq.cummax()
    held = net[s > 0]
    n_hedges = float((ledger["n_hedges"] * s).sum())
    return {
        "n_days": int(n),
        "occupancy": float((s > 0).mean()) if n else np.nan,
        "total_net_usd": float(net.sum()),
        "total_gross_usd": float(gross.sum()),
        "carry_usd": float(carry.sum()),
        "harvest_usd": float(harvest.sum()),
        "mtm_usd": float(mtm.sum()),
        "cost_usd": float((fee + gate_fee).sum()),
        "carry_bp": float(carry.sum() / package_dv01_usd),
        "harvest_bp": float(harvest.sum() / package_dv01_usd),
        "mtm_bp": float(mtm.sum() / package_dv01_usd),
        "net_bp": float(net.sum() / package_dv01_usd),
        "net_ex_mtm_usd": float(net_ex_mtm.sum()),
        "net_ex_mtm_bp": float(net_ex_mtm.sum() / package_dv01_usd),
        "sharpe_ex_mtm": sharpe_ex_mtm,
        "avg_daily_usd": mu,
        "daily_vol_usd": sd,
        "sharpe": sharpe,
        "skew": float(net.skew()) if n > 3 else np.nan,
        "hit_rate": float((held > 0).mean()) if len(held) else np.nan,
        "max_dd_usd": float(dd.min()) if n else np.nan,
        "worst_day_usd": float(net.min()) if n else np.nan,
        "n_hedges": n_hedges,
        "n_rolls": float((ledger["n_rolls"] * s).sum()),
        "n_years": (n / BUSINESS_DAYS) if n else np.nan,
        "equity": eq,
        "net_daily": net,
    }


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------


def unit_ledgers_for_pair(curve_map: dict, short: str, long: str,
                          variants: Sequence[dict], *,
                          package_dv01_usd: float = 100_000.0,
                          roll_months_set: Sequence[int] = (12,),
                          market: str = "USD",
                          curve_name: str = "USD-SOFR-1D") -> Dict[tuple, pd.DataFrame]:
    """Every hedging variant of one pair, off ONE set of warm ``CurvePricer``s.

    The expensive work — building the aged package and repricing its unit NPV,
    unit roll and unit DV01 on every date — is identical for every
    ``(hedge_threshold_bp, beta, resize_mode)`` combination, and ``CurvePricer``
    caches all three per date. Only ``roll_months`` changes the segmentation
    and therefore the packages. So one cold pass per (pair, roll_months) buys
    every threshold/beta/resize variant essentially free: measured 8.3s cold vs
    0.25s warm for a 254-day segment.

    Returns ``{(roll_months, threshold, beta, resize_mode): stitched ledger}``
    at ZERO cost — fees are applied later by ``book_stats``/``recost`` so a
    path is never re-run to change a cost assumption.
    """
    from RVUtils.StrikelessVol.costs import CostSchedule
    from RVUtils.StrikelessVol.replication import CurvePricer

    free = CostSchedule(multiplier=0.0)
    pair = forward_pair(short, long, market=market, curve_name=curve_name)
    days = sorted(k for k, v in curve_map.items() if v is not None and k != "live")
    out: Dict[tuple, pd.DataFrame] = {}
    base_cfg = Strat3Config(short_leg=short, long_leg=long, market=market,
                            curve_name=curve_name, package_dv01_usd=package_dv01_usd)
    for rm in roll_months_set:
        segs = roll_segments(days, rm)
        per_variant: Dict[tuple, List[pd.DataFrame]] = {}
        for (i, j) in segs:
            seg_days = days[i:j + 1]
            ctx = CurvePricer({d: curve_map[d] for d in seg_days}, pair,
                              package_dv01_usd=package_dv01_usd)
            for v in variants:
                cfg = base_cfg.with_(roll_months=rm, **v)
                key = (rm, cfg.hedge_threshold_bp, cfg.beta, cfg.resize_mode)
                per_variant.setdefault(key, []).append(
                    simulate_strat3(ctx, seg_days, cfg, free))
        for key, frames in per_variant.items():
            out[key] = stitch_segments(frames)
    return out


def grid_cells(pairs: Sequence[Tuple[str, str]],
               thresholds: Sequence[float],
               resize_modes: Sequence[str],
               betas: Sequence[float],
               roll_months_set: Sequence[int],
               entry_rules: Sequence[dict]) -> List[dict]:
    """The cartesian grid, as a list of override dicts."""
    cells = []
    for (s, l) in pairs:
        for rm in roll_months_set:
            for th in thresholds:
                for mode in resize_modes:
                    for b in betas:
                        for er in entry_rules:
                            cells.append(dict(short_leg=s, long_leg=l, roll_months=rm,
                                              hedge_threshold_bp=th, resize_mode=mode,
                                              beta=b, **er))
    return cells


def run_grid(ledgers: Dict[tuple, Dict[tuple, pd.DataFrame]],
             screens: Dict[str, pd.DataFrame],
             cells: Sequence[dict],
             *, package_dv01_usd: float = 100_000.0,
             cost_multiplier: float = 1.0,
             window: Optional[Tuple[dt.date, dt.date]] = None) -> pd.DataFrame:
    """Score every grid cell off precomputed unit ledgers. No repricing."""
    rows = []
    for cell in cells:
        cfg = Strat3Config(package_dv01_usd=package_dv01_usd,
                           cost_multiplier=cost_multiplier, **cell)
        pkey = (cfg.short_leg, cfg.long_leg)
        vkey = (cfg.roll_months, cfg.hedge_threshold_bp, cfg.beta, cfg.resize_mode)
        led = ledgers.get(pkey, {}).get(vkey)
        if led is None or not len(led):
            continue
        if window is not None:
            led = led[(led.index >= pd.Timestamp(window[0])) & (led.index <= pd.Timestamp(window[1]))]
            if not len(led):
                continue
        scr = screens.get(cfg.pair_name)
        state = None if cfg.entry_rule == "always" else entry_state(scr, cfg, led.index)
        costs = cost_schedule_for(cfg.short_leg, cfg.long_leg, multiplier=cost_multiplier)
        st = book_stats(led, state, costs=costs, package_dv01_usd=package_dv01_usd)
        st.pop("equity", None)
        st.pop("net_daily", None)
        row = {"pair": cfg.pair_name, "short_leg": cfg.short_leg, "long_leg": cfg.long_leg,
               "roll_months": cfg.roll_months, "threshold_bp": cfg.hedge_threshold_bp,
               "resize_mode": cfg.resize_mode, "beta": cfg.beta,
               "entry_rule": cfg.entry_rule, "z_window": cfg.z_window,
               "z_min": cfg.z_min, "be_ratio_max": cfg.be_ratio_max,
               "citi_fig4_sharpe": CITI_FIG4_SHARPE.get(pkey, np.nan)}
        # ex-ante screen averages: the "is this cell long vol AND paid?" columns
        if scr is not None and len(scr):
            w = scr if window is None else scr[(scr.index >= pd.Timestamp(window[0]))
                                               & (scr.index <= pd.Timestamp(window[1]))]
            row["mean_carry_1y_bp"] = float(w["carry_1y_bp"].mean())
            row["pct_days_carry_positive"] = float((w["carry_1y_bp"] >= 0).mean())
            row["mean_gamma_usd_bp2"] = float(w["gamma_usd_bp2"].mean())
            row["mean_be_over_rv"] = float(w["be_over_rv"].mean())
            row["mean_level_bp"] = float(w["level_bp"].mean())
        row.update(st)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Trade schedule for the engine-native (QueryDrivenBacktest) run
# ---------------------------------------------------------------------------


def hedge_schedule(curve_map: dict, cfg: Strat3Config) -> pd.DataFrame:
    """The exact trade tape the strategy produces, for replay in the engine.

    One row per traded event with everything ``IRSwapQuery`` needs:
    ``kind`` in {initiate, hedge, roll}, the two legs' effective/maturity dates
    (so an increment is struck on the AGED leg's own dates, not on a fresh
    constant-maturity forward), and the ``bpv`` to trade.

    Citi resizes the initial off-market swap; the engine cannot hold a negative
    increment of an existing position, so the increment is booked as a separate
    AT-MARKET swap on the same dates. Citi names that as the practical
    implementation of the same trade (Doc A l.140: "we adjust the notional of
    the initial off-market swap, although delta-hedging with ATM swaps may be
    easier for the practical implementation of this strategy").
    """
    from RVUtils.StrikelessVol.costs import CostSchedule
    from RVUtils.StrikelessVol.replication import CurvePricer

    free = CostSchedule(multiplier=0.0)
    pair = forward_pair(cfg.short_leg, cfg.long_leg, market=cfg.market,
                        curve_name=cfg.curve_name)
    days = sorted(k for k, v in curve_map.items() if v is not None and k != "live")
    segs = roll_segments(days, cfg.roll_months)
    rows = []
    for k, (i, j) in enumerate(segs):
        seg_days = days[i:j + 1]
        curves = {d: curve_map[d] for d in seg_days}
        ctx = CurvePricer(curves, pair, package_dv01_usd=cfg.package_dv01_usd)
        led = simulate_strat3(ctx, seg_days, cfg, free)
        pkg = ctx.package
        c0 = curves[seg_days[0]]
        legs = {}
        for name, swap in (("short", pkg.short), ("long", pkg.long)):
            legs[name] = {
                "effective": pd.Timestamp(c0.effective_date(swap)).date(),
                "maturity": pd.Timestamp(c0.maturity_date(swap)).date(),
                "built_notional": float(c0.notional(swap)),
            }
        # opening trade. bpv is the leg's TRUE dollars-per-bp, in the query
        # layer's convention (bpv > 0 = PAYER): pay the short leg, receive the
        # long leg, so the flattener is (+DV01, -beta*DV01).
        d0 = pd.Timestamp(seg_days[0])
        kind0 = "initiate" if k == 0 else "roll"
        for name, bpv in (("short", +cfg.package_dv01_usd),
                          ("long", -cfg.package_dv01_usd * cfg.beta)):
            rows.append({"segment": k, "date": d0.date(), "kind": kind0, "leg": name,
                         "bpv": bpv,
                         "effective": legs[name]["effective"],
                         "maturity": legs[name]["maturity"]})
        # hedges: the increment IS d(n_long) of the aged long leg, so its
        # dollars-per-bp is exactly d(n_long) * that leg's per-unit dv01.
        dn = led["long_notional"].diff().fillna(0.0)
        for d, delta in dn[dn != 0.0].items():
            rows.append({"segment": k, "date": pd.Timestamp(d).date(), "kind": "hedge",
                         "leg": "long",
                         "bpv": -float(delta * ctx.dv01(d, "long")),
                         "effective": legs["long"]["effective"],
                         "maturity": legs["long"]["maturity"]})
        rows.append({"segment": k, "date": pd.Timestamp(seg_days[-1]).date(),
                     "kind": "unwind", "leg": "both", "bpv": np.nan,
                     "effective": None, "maturity": None})
    return pd.DataFrame(rows)


def _as_date(d) -> dt.date:
    if isinstance(d, dt.datetime):
        return d.date()
    if isinstance(d, dt.date):
        return d
    return pd.Timestamp(d).date()
