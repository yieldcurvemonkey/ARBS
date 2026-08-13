"""Configuration for the cross-currency basis RV book.

Every default is the value in ``jpm_pfin/RVPF/signal_building.py``; the original name is recorded
against each. That file is a script, not a module, so these are read off its top-level assignments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Sequence, Tuple

#: ``swap_maturities`` — forward-start point (years) -> underlying swap maturity (years).
DEFAULT_POINTS: Dict[int, int] = {1: 1, 2: 1, 3: 1, 5: 5}

#: ``currency_pairs`` — the universe RVPF banked. Every one is quotable in ARBS via Citi except
#: EURJPY, which is synthesised from the two USD crosses exactly as the original does.
DEFAULT_PAIRS: Tuple[str, ...] = ("USDEUR", "USDGBP", "USDJPY", "USDCAD", "EURJPY")


@dataclass(frozen=True)
class SignalConfig:
    """The five signals, their windows, and their blend weights."""

    #: ``carry_horizon`` — the roll-down horizon, in years.
    carry_horizon: float = 0.25
    #: ``vol_halflife`` — EWM std halflife on daily returns; also the annualisation window.
    vol_halflife: int = 63
    #: ``carry_shift`` — lag used for the day-on-day change in carry.
    carry_shift: int = 1
    #: ``carry_change_halflife`` — smoothing on that change.
    carry_change_halflife: int = 21
    #: ``momentum_halflife_st`` / ``_lt`` — the fast and slow EWMAs of the 6m basis.
    momentum_halflife_st: int = 5
    momentum_halflife_lt: int = 63
    #: ``signal_scoring_halflife`` — EWM std used to score each raw signal.
    scoring_halflife: int = 126
    #: ``signal_smoothing_halflife`` — optional post-scoring smoothing; None in the original.
    smoothing_halflife: int | None = None
    #: ``outliers_std`` — daily returns beyond this many sample sds are zeroed.
    outliers_std: float = 5.0

    #: ``signal{1..5}_weight``. Only signal 1 is on in the original's shipped configuration.
    weights: Tuple[float, float, float, float, float] = (1.0, 0.0, 0.0, 0.0, 0.0)

    @property
    def active(self) -> Tuple[int, ...]:
        return tuple(i + 1 for i, w in enumerate(self.weights) if w != 0.0)


@dataclass(frozen=True)
class OptimizerConfig:
    """``opto.mean_variance(...)`` arguments."""

    #: ``risk_param``
    risk_aversion: float = 1750.0
    #: ``transaction_costs`` — per unit change in holding. 0.5bp in the original.
    transaction_costs: float = 0.5 / 10_000.0
    #: ``transaction_cost_aversion``
    transaction_cost_aversion: float = 50.0
    #: ``full_cov`` — the original defaults to a DIAGONAL covariance built from each instrument's
    #: own EWM vol; the full rolling covariance is available but off.
    full_covariance: bool = False
    #: ``cov_halflife`` — window for the full covariance when enabled.
    cov_window: int = 252
    #: Use the ported cvxopt optimizer. When False the book uses the closed-form diagonal
    #: no-trade band, which is the *exact* optimum of the same problem when the covariance is
    #: diagonal and there are no constraints — and which, unlike the QP, works for one asset.
    use_cvxopt: bool = False


@dataclass(frozen=True)
class BacktestConfig:
    #: NOTIONAL per unit of holding, in currency. The original works in decimal return space and
    #: leaves the scale implicit; making it explicit is what lets the engine mark in dollars.
    #:
    #: The DV01 follows from it -- ``notional / 10_000`` -- and getting that conversion wrong is
    #: not a rounding error: treating this number as $/bp rather than notional inflates every fee
    #: by 10,000x, which on this panel produced $307m of costs against $22k of gross P&L.
    notional_per_unit: float = 1_000_000.0

    @property
    def dv01_per_unit(self) -> float:
        """Currency per basis point, per unit of holding."""
        return self.notional_per_unit / 10_000.0
    #: Round-trip cost charged at unwind, in bp of basis. ARBS has NO measured cost line for
    #: cross-currency basis, so this is the original's assumption carried forward and flagged.
    round_trip_bp: float = 1.0
    #: Rebalance cadence in business days.
    rebalance_every: int = 1
    #: Minimum |holding| change before an order is emitted, as a fraction of the target.
    min_trade_fraction: float = 0.10


@dataclass(frozen=True)
class XccyConfig:
    name: str = "xccy_rv"
    pairs: Tuple[str, ...] = DEFAULT_PAIRS
    points: Dict[int, int] = field(default_factory=lambda: dict(DEFAULT_POINTS))
    reference_currency: str = "USD"
    #: ``carry_returns`` — use the banked returns that include carry, rather than price-only.
    carry_returns: bool = True
    signal: SignalConfig = field(default_factory=SignalConfig)
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)

    def instruments(self) -> Sequence[str]:
        return [f"{p} {f}Yx{self.points[f]}Y" for p in self.pairs for f in sorted(self.points)]

    def describe(self) -> str:
        s = self.signal
        return (
            f"{self.name}: {len(self.pairs)} pairs x {len(self.points)} points, "
            f"signals {s.active} (weights {s.weights}), vol hl={s.vol_halflife}, "
            f"score hl={s.scoring_halflife}, lambda={self.optimizer.risk_aversion:g}, "
            f"tc={self.optimizer.transaction_costs * 1e4:.2f}bp x {self.optimizer.transaction_cost_aversion:g}"
        )
