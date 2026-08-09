"""Core types for the SR3-vs-ZQ distribution-comparison screener."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class RegimeBucket(Enum):
    CALM = "calm"
    STRESS = "stress"
    PIVOT = "pivot"
    HIKE = "hike"


class TradeFlagKind(Enum):
    """The four trade families from spec §3."""

    VOL_CONE = "vol_cone"               # variance RV (sell SR3 straddle vs ZQ tree)
    SKEW = "skew"                       # directional disagreement (SR3 RR vs FedWatch)
    TAIL = "tail"                       # surprise component (SR3 wing vs ZQ tree-tail-zero)
    CROSS_QUARTER = "cross_quarter"     # term structure of residual variance
    LAMBDA_DEPENDENCE = "lambda_dependence"  # the copula coordinate vs a prior
    LAMBDA_ARBITRAGE = "lambda_arbitrage"    # RND variance outside EVERY coupling's reach


@dataclass(frozen=True)
class TradeFlag:
    """A single signal-triggered trade flag with severity."""

    kind: TradeFlagKind
    severity_decile: int     # 1-10; 9-10 = top decile, 1-2 = bottom (extremes both flag)
    direction: str           # "buy_vol", "sell_vol", "long_call_skew", "long_put_skew", "long_tail", etc.
    rationale: str           # human-readable: "SR3 ATM var 95th-pctl vs ZQ tree+drift"
    severity_value: float    # raw signal value
    severity_threshold: float  # threshold the signal crossed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity_decile": self.severity_decile,
            "direction": self.direction,
            "rationale": self.rationale,
            "severity_value": self.severity_value,
            "severity_threshold": self.severity_threshold,
        }


@dataclass(frozen=True)
class MonthState:
    """ZQ FedWatch state per month (per CME methodology)."""

    label: str                            # e.g., "jun26"
    contract: str                         # e.g., "ZQM26"
    avg_effr: float                       # implied avg EFFR (decimal)
    has_meeting: bool
    meeting_date: Optional[datetime.date]
    days_in_month: int
    days_before_meeting: int
    days_after_meeting: int
    effr_start: float = float("nan")      # solved start-of-month EFFR
    effr_end: float = float("nan")        # solved end-of-month EFFR

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "contract": self.contract,
            "avg_effr": self.avg_effr,
            "has_meeting": self.has_meeting,
            "meeting_date": self.meeting_date.isoformat() if self.meeting_date else None,
            "days_in_month": self.days_in_month,
            "days_before_meeting": self.days_before_meeting,
            "days_after_meeting": self.days_after_meeting,
            "effr_start": self.effr_start,
            "effr_end": self.effr_end,
        }


@dataclass(frozen=True)
class MeetingNode:
    """One node of the FedWatch binary probability tree."""

    label: str
    date: datetime.date
    prior_effr: float                # start-of-meeting-month EFFR
    next_effr: float                 # end-of-meeting-month EFFR
    expected_change_bp: float        # bp move
    char_25bp: int                   # integer multiple of 25bp
    mantissa: float                  # remainder
    p_lower: float                   # P(char × 25bp move)
    p_upper: float                   # P((char + sign) × 25bp move)
    variance_bp2: float              # binomial variance in bp²

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "date": self.date.isoformat(),
            "prior_effr": self.prior_effr,
            "next_effr": self.next_effr,
            "expected_change_bp": self.expected_change_bp,
            "char_25bp": self.char_25bp,
            "mantissa": self.mantissa,
            "p_lower": self.p_lower,
            "p_upper": self.p_upper,
            "variance_bp2": self.variance_bp2,
        }


@dataclass(frozen=True)
class FedWatchTree:
    """Full FedWatch tree as built from ZQ prices + FOMC schedule."""

    as_of: datetime.date
    months: Tuple[MonthState, ...]
    nodes: Tuple[MeetingNode, ...]
    spot_effr: float


@dataclass(frozen=True)
class SignalRecord:
    """Per-(as_of, contract) signal output."""

    as_of: datetime.date
    sr3_contract: str
    sr3_dte: int
    ref_start: datetime.date
    ref_end: datetime.date
    forward_price: float
    forward_rate: float

    # FedWatch tree
    n_meetings_in_period: int
    fedwatch_meeting_labels: Tuple[str, ...]
    fedwatch_expected_changes_bp: Tuple[float, ...]

    # Variance decomposition (bp²)
    sr3_total_var_bp2: float
    zq_day_weighted_var_bp2: float
    intermeeting_drift_var_bp2: float
    basis_var_bp2: float
    explained_var_bp2: float
    residual_var_bp2: float
    residual_to_explained_ratio: float

    # SR3 RND moments
    sr3_skew: float
    sr3_kurt: float

    # Tail mass at ±50/75/100bp from forward
    tail_lower_50: float
    tail_lower_75: float
    tail_lower_100: float
    tail_upper_50: float
    tail_upper_75: float
    tail_upper_100: float

    # Stability + λ
    stability_flag: str
    smoothing_sensitivity_pp: float
    negative_density_pct: float
    chosen_lambda: float
    n_strikes_used: int
    prices_source: str

    # Regime + flags
    regime_bucket: RegimeBucket
    flags: Tuple[TradeFlag, ...]

    warnings: Tuple[str, ...] = ()

    # Copula coordinate. Defaults are NaN so a record built without it is unchanged, and so a
    # session where the measurement is inapplicable reports "not measured" rather than 0.
    lambda_wing: float = float("nan")
    lambda_wing_strict: float = float("nan")
    lambda_var: float = float("nan")
    lambda_atom_spread: float = float("nan")
    lambda_ok: bool = False
    lambda_reason: str = ""
    wing_comonotone: float = float("nan")
    wing_independent: float = float("nan")
    wing_min_variance: float = float("nan")
    wing_observed: float = float("nan")
    var_comonotone_bp2: float = float("nan")
    var_independent_bp2: float = float("nan")
    var_min_variance_bp2: float = float("nan")
    hard_violation_bp2: float = float("nan")
    lambda_basis_var_share: float = float("nan")
    trough_peak_ratio: float = float("nan")
    lambda_mode_prices: Tuple[float, ...] = ()
    lambda_marginals: Tuple[float, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "sr3_contract": self.sr3_contract,
            "sr3_dte": self.sr3_dte,
            "ref_start": self.ref_start.isoformat(),
            "ref_end": self.ref_end.isoformat(),
            "forward_price": self.forward_price,
            "forward_rate": self.forward_rate,
            "n_meetings_in_period": self.n_meetings_in_period,
            "fedwatch_meeting_labels": list(self.fedwatch_meeting_labels),
            "fedwatch_expected_changes_bp": list(self.fedwatch_expected_changes_bp),
            "sr3_total_var_bp2": self.sr3_total_var_bp2,
            "zq_day_weighted_var_bp2": self.zq_day_weighted_var_bp2,
            "intermeeting_drift_var_bp2": self.intermeeting_drift_var_bp2,
            "basis_var_bp2": self.basis_var_bp2,
            "explained_var_bp2": self.explained_var_bp2,
            "residual_var_bp2": self.residual_var_bp2,
            "residual_to_explained_ratio": self.residual_to_explained_ratio,
            "sr3_skew": self.sr3_skew,
            "sr3_kurt": self.sr3_kurt,
            "tail_lower_50": self.tail_lower_50,
            "tail_lower_75": self.tail_lower_75,
            "tail_lower_100": self.tail_lower_100,
            "tail_upper_50": self.tail_upper_50,
            "tail_upper_75": self.tail_upper_75,
            "tail_upper_100": self.tail_upper_100,
            "stability_flag": self.stability_flag,
            "smoothing_sensitivity_pp": self.smoothing_sensitivity_pp,
            "negative_density_pct": self.negative_density_pct,
            "chosen_lambda": self.chosen_lambda,
            "n_strikes_used": self.n_strikes_used,
            "prices_source": self.prices_source,
            "regime_bucket": self.regime_bucket.value,
            "flags": [f.to_dict() for f in self.flags],
            "warnings": list(self.warnings),
            "lambda_wing": self.lambda_wing,
            "lambda_wing_strict": self.lambda_wing_strict,
            "lambda_var": self.lambda_var,
            "lambda_atom_spread": self.lambda_atom_spread,
            "lambda_ok": self.lambda_ok,
            "lambda_reason": self.lambda_reason,
            "wing_comonotone": self.wing_comonotone,
            "wing_independent": self.wing_independent,
            "wing_min_variance": self.wing_min_variance,
            "wing_observed": self.wing_observed,
            "var_comonotone_bp2": self.var_comonotone_bp2,
            "var_independent_bp2": self.var_independent_bp2,
            "var_min_variance_bp2": self.var_min_variance_bp2,
            "hard_violation_bp2": self.hard_violation_bp2,
            "lambda_basis_var_share": self.lambda_basis_var_share,
            "trough_peak_ratio": self.trough_peak_ratio,
            "lambda_mode_prices": list(self.lambda_mode_prices),
            "lambda_marginals": list(self.lambda_marginals),
        }


@dataclass
class DistributionScreenerConfig:
    """User-tunable configuration."""

    # Universe (which SR3 contracts to evaluate)
    sr3_contracts: Optional[Tuple[str, ...]] = None  # None ⇒ auto-resolve nearest 3 quarterlies
    dte_floor: int = 60
    dte_ceiling: int = 200

    # SR3 reference period helper
    ref_period_days: int = 91  # standard IMM 3M window

    # SOFR-EFFR basis (constant for v1; configurable callable in future)
    basis_bp: float = 0.0
    basis_var_bp2: float = 0.0

    # Intermeeting daily SOFR vol assumption
    intermeeting_daily_vol_bp: float = 0.3

    # RND extraction (delegates to STIRAsymmetricScreener._rnd)
    rnd_smoothing_param: float = 1e-4
    rnd_spline_order: int = 4
    rnd_n_ghost_points: int = 10

    # λ optimization
    optimize_lambda: bool = True
    lambda_grid: Tuple[float, ...] = (1e-5, 5e-5, 1e-4, 5e-4, 1e-3)
    lambda_grid_stress: Tuple[float, ...] = (1e-6, 5e-6, 1e-5, 5e-5, 1e-4)

    # Regime classifier thresholds — calibrated from 18-date backfill quantiles
    # (3 calm + 3 stress + 4 pivot + 7 hike samples spanning 2022 hike cycle
    # through 2026 current).
    regime_residual_ratio_stress_p25: float = 60.0     # stress p25=84; buffer below
    regime_tail_upper_50bp_stress_p25: float = 0.20    # stress p25=0.20
    regime_skew_pivot_p75: float = -1.0                # pivot p75=-1.37; hike p75=-0.24
    regime_skew_calm_p25: float = 0.20                 # calm p25=-0.38; not currently gated

    # Trade flag thresholds (per spec §3)
    vol_cone_residual_ratio_pctl: float = 0.90    # top decile residual ratio = sell vol
    skew_zscore_threshold: float = 1.5            # SR3 RR Z-score |≥ 1.5σ|
    tail_upper_50bp_threshold: float = 0.15       # tail mass ≥ 15% at ±50bp = stress hedge
    cross_quarter_min_contracts: int = 3          # need ≥ 3 SR3 contracts for term-structure

    # Data sources
    options_source: str = "BARCHART_STIRFO-QL"
    futures_source: str = "BARCHART_STIRF-RL"
    curve_source: str = "BARCHART_STIRF-RL"
    curve_name: str = "USD-SOFR-1D-Q12STIRT"

    # Output
    output_root: str = "data/screener_results/sr3_zq_distribution_screener"
    random_seed: int = 17
