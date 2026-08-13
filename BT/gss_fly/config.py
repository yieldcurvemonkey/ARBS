"""Configuration for the GSS cash-bond butterfly book.

Every parameter here is taken from the source it was ported from —
``jpm_pfin/RelativeValue/ag_processes/CURVE_FITTING/python/GSS/GSS_main.py`` — and the docstring
records the original name. Three settings are **deliberate deviations**; each is a knob and each
carries the reason inline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Tuple

# ``BASIS`` in GSS_module.py — repo accrues on a 360-day year.
REPO_BASIS = 360.0

WingObjective = Literal["signal_gap", "legacy_ttm_bug"]
CostLegs = Literal["all", "belly_only"]


@dataclass(frozen=True)
class BondSignalConfig:
    """Bond-level richness score: ``Signal = w·TSscore + (1-w)·XSscore``."""

    #: ``signal_weights`` — weight on the time-series score; the cross-section gets ``1 - w``.
    ts_weight: float = 0.75
    #: ``my_smoothing_window`` — EWMA **halflife** on the per-bond spread-to-curve.
    smoothing_halflife: float = 3.0
    #: ``my_scoring_window`` — the original passes this POSITIONALLY to ``pd.ewma``/``pd.ewmstd``,
    #: so in pandas 0.x it binds to ``com``, not ``halflife``. Reproduced as ``com`` on purpose.
    scoring_com: float = 20.0


@dataclass(frozen=True)
class UniverseConfig:
    """``select_eligible_bonds`` filters."""

    #: ``max_coupon`` — percent.
    max_coupon: float = 7.0
    #: ``min_ttm`` — years.
    min_ttm: float = 3.0
    #: ``min_issue_time`` = 2.5 * 20 = 50 calendar days of seasoning.
    min_seasoning_days: float = 50.0
    #: ``small_issue_time`` — bonds issued inside this window are kept regardless of size.
    recent_issue_days: float = 3 * 365.25
    #: Ranks to drop. ARBS marks on-the-runs ``rank == 0``; GSS had no rank concept, but an OTR
    #: bond carries a specialness the GC repo hurdle does not price, so it is excluded by default.
    exclude_ranks: Tuple[int, ...] = (0,)


@dataclass(frozen=True)
class FlyConfig:
    """``build_flies`` / ``wing_selection`` / ``build_weights``."""

    #: ``maturity_buckets`` — belly TTM bucket upper bounds.
    maturity_window_1: float = 10.0
    maturity_window_2: float = 20.0
    #: ``wing_ranges`` — the +/- TTM window wings are drawn from, per bucket.
    wing_range_1: float = 2.0
    wing_range_2: float = 5.0
    #: Beyond ``maturity_window_2`` the original searches left from 20y and right to belly+100y.
    long_end_right_reach: float = 100.0

    #: ``std_hl`` — EWM std halflife on the fly yield (bp), the vol in ``ZSig``.
    std_halflife: float = 20.0
    #: ``s2c_hl_smoothing`` / ``s2c_hl_scoring`` — fly-level z of the spread-to-curve.
    fly_smoothing_halflife: float = 2.0
    fly_scoring_com: float = 30.0

    #: DEVIATION 1. ``wing_selection`` in the original maximises
    #: ``|Signal_wing - belly.TimeToMaturity|`` — a z-score minus a maturity in years, which is
    #: almost certainly a typo for ``Signal_belly``. ``signal_gap`` is the corrected objective;
    #: ``legacy_ttm_bug`` reproduces the original exactly for tie-out work.
    wing_objective: WingObjective = "signal_gap"

    #: Cap on candidate bellies scanned per date (the original scans every eligible bond).
    max_bellies_per_date: int = 0  # 0 == no cap


#: Half-spreads MEASURED from FedInvest's own bid/offer, priced to yield on 1,890 note/bond quotes
#: across 6 dates in 2025 (`scripts/gss_measure_cost_table.py`). Medians per bucket.
#:
#: The shape is the finding. The default table rises monotonically with maturity; the market's is
#: **U-shaped** — widest at the front (0.63bp, 3x the assumption) and TIGHTEST in 7-10y (0.11bp, a
#: quarter of it), because 0-3y is dominated by heavily seasoned issues nobody trades while 7-10y is
#: the actively quoted benchmark sector. The 20y+ assumption is 5x too punitive.
#:
#: Net effect is small: overall median half-spread 0.326bp, so a 3-leg fly (|w| summing to 2) costs
#: ~1.31bp round trip measured against ~1.66bp charged — the book was overcharged by about 21%,
#: which does not begin to close a gap where costs are 4.5x gross and break-even needs 0.37bp.
MEASURED_HALF_SPREAD_BP: Dict[float, float] = {
    0.0: 0.625, 3.0: 0.244, 5.0: 0.156, 7.0: 0.111, 10.0: 0.368, 20.0: 0.161,
}


@dataclass(frozen=True)
class CostConfig:
    """``fly_tcost`` plus the repo hurdle."""

    #: One-way bid/offer in **bp of yield**, keyed by the lower edge of a TTM bucket.
    #: The original carried a country-specific calibrated table; none survived, so this default is
    #: transparent rather than measured. See :data:`MEASURED_HALF_SPREAD_BP` for one derived from
    #: FedInvest's own quoted bid/offer, and `scripts/gss_measure_cost_table.py` for how.
    half_spread_bp: Dict[float, float] = field(
        default_factory=lambda: {0.0: 0.20, 3.0: 0.25, 5.0: 0.30, 7.0: 0.40, 10.0: 0.50, 20.0: 0.80}
    )
    #: DEVIATION 2. ``fly_tcost`` returns ``my_tcosts.iloc[fly_ttm_buckets[1]]`` — the **belly's**
    #: bucket only, and its docstring says so ("the total t-cost of a fly is given by the cost of
    #: buying / selling the body bond"). Charging two wings for free flatters the book, so the
    #: default here charges every leg weighted by |w|. ``belly_only`` restores the original.
    cost_legs: CostLegs = "all"
    #: ``repo_pen`` — the vol-scaled signal (bp) below which a position is no longer worth its
    #: financing, and the exit fires.
    repo_penalty_bp: float = 2.5
    #: Fallback GC repo rate (percent) when no repo curve is supplied.
    fallback_repo_pct: float = 4.30


@dataclass(frozen=True)
class BacktestConfig:
    """``run_backtest`` gates."""

    #: ``std_threshold`` — entry fires when ``ZSig = |z|·σ_fly`` exceeds this, in bp.
    #: GSS_main calls run_backtest twice; the live call passes 3.0.
    entry_zsig_bp: float = 3.0
    #: ``zscore_exit_threshold`` — |z| below which a rolling-over fly is closed.
    exit_abs_z: float = 0.5
    #: ``zscore_entry_threshold`` — retained for the commented-out alternate entry gate.
    entry_abs_z: float = 1.0
    #: The original requires ``Diff-Zscore < 0`` at entry: |z| must already be shrinking, so the
    #: book buys the turn rather than the extreme.
    require_turning_point: bool = True
    #: Concurrent flies. The original has no cap; a cap keeps the QDB run bounded.
    max_concurrent: int = 10
    #: Belly risk per fly, $/bp. Sizing is by belly BPV; wings follow the maturity weights.
    belly_bpv: float = 100_000.0
    #: Minimum business days between re-entering the same fly id.
    reentry_cooldown_days: int = 5


@dataclass(frozen=True)
class GSSConfig:
    name: str = "gss_fly"
    signal: BondSignalConfig = field(default_factory=BondSignalConfig)
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    fly: FlyConfig = field(default_factory=FlyConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)

    def describe(self) -> str:
        d = self
        return (
            f"{d.name}: signal {d.signal.ts_weight:.2f}·TS + {1 - d.signal.ts_weight:.2f}·XS "
            f"(smooth hl={d.signal.smoothing_halflife:g}, score com={d.signal.scoring_com:g}) | "
            f"universe cpn<{d.universe.max_coupon:g} ttm>={d.universe.min_ttm:g} "
            f"season>={d.universe.min_seasoning_days:g}d | "
            f"wings {d.fly.wing_objective} ±{d.fly.wing_range_1:g}/{d.fly.wing_range_2:g}y | "
            f"entry ZSig>{d.backtest.entry_zsig_bp:g}bp exit<={d.costs.repo_penalty_bp:g}bp | "
            f"costs {d.costs.cost_legs}"
        )
