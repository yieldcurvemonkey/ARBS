import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np


@dataclass(frozen=True)
class RNDInput:
    """Market inputs used for density extraction."""

    symbol: str
    as_of: datetime.date
    forward_price: float
    forward_rate: float
    time_to_expiry: float
    expiry_date: datetime.date
    discount_factor: float
    strikes_price: np.ndarray
    call_premiums: np.ndarray
    strike_source: str

    def __repr__(self) -> str:
        return (
            f"RNDInput(symbol={self.symbol!r}, as_of={self.as_of}, "
            f"fwd_rate={self.forward_rate:.4f}, tte={self.time_to_expiry:.4f}, "
            f"n_strikes={len(self.strikes_price)})"
        )


@dataclass(frozen=True)
class BreedenLitzenbergerResult:
    """Output of the Breeden-Litzenberger smoothing spline approach."""

    input: RNDInput
    # Fine grid (rate space, ascending)
    strike_grid_rate: np.ndarray
    rnd_density: np.ndarray
    rnd_cumulative: np.ndarray
    # Binned scenario probabilities
    bin_edges_rate: np.ndarray
    bin_probabilities: np.ndarray
    bin_labels: List[str]
    # Summary statistics
    mean_rate: float
    std_rate: float
    skewness: float
    kurtosis: float
    # Diagnostics
    smoothing_param: float
    n_ghost_points: int
    spline_residual: float
    warnings: Tuple[str, ...] = ()

    def percentile(self, p: float) -> float:
        """Return the rate at the p-th percentile (0-100), linearly interpolated."""
        return float(np.interp(p / 100.0, self.rnd_cumulative, self.strike_grid_rate))


@dataclass(frozen=True)
class BKMResult:
    """Output of the Bakshi-Kapadia-Madan model-free moments approach.

    Moments are computed via integration of option prices (smoothing operation),
    avoiding the noise amplification of Breeden-Litzenberger's differentiation.
    """

    input: RNDInput
    # Rate-space moments (R = 100 - P)
    variance_rate: float
    std_rate: float
    skewness_rate: float
    kurtosis_rate: float
    excess_kurtosis_rate: float
    # Raw price-space central moments
    mu2_price: float
    mu3_price: float
    mu4_price: float
    # Tail diagnostics
    left_tail_variance_frac: float
    right_tail_variance_frac: float
    n_otm_calls: int
    n_otm_puts: int
    warnings: Tuple[str, ...] = ()

    @property
    def mean_rate(self) -> float:
        """The futures forward rate IS the risk-neutral mean — no estimation needed."""
        return self.input.forward_rate


@dataclass(frozen=True)
class ScenarioDefinition:
    """A single scenario for the Gaussian mixture approach."""

    label: str
    mean_rate: float
    std_rate: Optional[float] = None  # None → optimized during calibration


@dataclass(frozen=True)
class GaussianMixtureResult:
    """Output of the Gaussian mixture scenario decomposition."""

    input: RNDInput
    scenarios: Tuple[ScenarioDefinition, ...]
    weights: np.ndarray
    fitted_std_rates: np.ndarray
    # Composite distribution on fine grid (rate space, ascending)
    strike_grid_rate: np.ndarray
    composite_density: np.ndarray
    composite_cdf: np.ndarray
    # Fit quality
    rmse_price: float
    max_abs_error_price: float
    optimization_success: bool
    # Per-scenario density components: shape (n_scenarios, n_grid_points)
    component_densities: np.ndarray
    warnings: Tuple[str, ...] = ()

    def scenario_weight_dict(self) -> Dict[str, float]:
        return {s.label: float(w) for s, w in zip(self.scenarios, self.weights)}


@dataclass(frozen=True)
class ImpliedDistributionSnapshot:
    """Combined result for a single contract/date."""

    symbol: str
    as_of: datetime.date
    bl_result: Optional[BreedenLitzenbergerResult]
    gm_result: Optional[GaussianMixtureResult]
    bkm_result: Optional["BKMResult"] = None

    def all_warnings(self) -> Tuple[str, ...]:
        """Return all child warnings prefixed with their source (``bl::`` / ``gm::`` / ``bkm::``)."""
        out: List[str] = []
        if self.bl_result is not None:
            out.extend(f"bl::{w}" for w in self.bl_result.warnings)
        if self.gm_result is not None:
            out.extend(f"gm::{w}" for w in self.gm_result.warnings)
        if self.bkm_result is not None:
            out.extend(f"bkm::{w}" for w in self.bkm_result.warnings)
        return tuple(out)


@dataclass(frozen=True)
class StripComparisonResult:
    """Combined result comparing implied distributions across a strip of contracts."""

    symbols: List[str]
    date_before: datetime.date
    date_after: datetime.date
    snapshots_before: Dict[str, ImpliedDistributionSnapshot]
    snapshots_after: Dict[str, ImpliedDistributionSnapshot]
    strip_label: Optional[str] = None  # e.g. "whites", "2y", or None for custom

    @property
    def n_contracts(self) -> int:
        return len(self.symbols)

    def forward_rates(self) -> Dict[str, Tuple[float, float]]:
        """Return {symbol: (fwd_before, fwd_after)} for contracts with BL results."""
        result: Dict[str, Tuple[float, float]] = {}
        for sym in self.symbols:
            bl1 = self.snapshots_before.get(sym)
            bl2 = self.snapshots_after.get(sym)
            if bl1 and bl1.bl_result and bl2 and bl2.bl_result:
                result[sym] = (bl1.bl_result.input.forward_rate, bl2.bl_result.input.forward_rate)
        return result


@dataclass(frozen=True)
class ViewMetadata:
    """Support / exactness label carried by analytical outputs."""

    support: str
    note: Optional[str] = None

    def display_label(self) -> str:
        if self.note:
            return f"{self.support} | {self.note}"
        return self.support


@dataclass(frozen=True)
class AnnotatedResult:
    """Generic result wrapper with lightweight provenance metadata."""

    data: Any
    metadata: ViewMetadata


@dataclass(frozen=True)
class FOMCPathState:
    """A common latent state represented as a piecewise-constant FOMC rate path."""

    label: str
    initial_rate: float
    meeting_dates: Tuple[datetime.date, ...]
    meeting_rates: Tuple[float, ...]
    metadata: Dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if len(self.meeting_dates) != len(self.meeting_rates):
            raise ValueError("meeting_dates and meeting_rates must have identical lengths")

    @property
    def terminal_rate(self) -> float:
        if self.meeting_rates:
            return float(self.meeting_rates[-1])
        return float(self.initial_rate)

    def rate_on(self, when: datetime.date) -> float:
        """Return the piecewise-constant policy rate in force on *when*."""
        if not self.meeting_dates:
            return float(self.initial_rate)
        idx = int(np.searchsorted(np.asarray(self.meeting_dates, dtype="datetime64[D]"), np.datetime64(when), side="right")) - 1
        if idx < 0:
            return float(self.initial_rate)
        return float(self.meeting_rates[idx])


@dataclass(frozen=True)
class FOMCPathStateConfig:
    """Configuration for the shared FOMC-path latent state library."""

    current_rate: float
    cut_size_bps: float = 25.0
    terminal_move_grid_bps: Tuple[int, ...] = (-100, -75, -50, -25, 0, 25, 50, 75, 100)
    n_plus_years: int = 2
    max_states: Optional[int] = None
    meeting_dates: Optional[Tuple[datetime.date, ...]] = None
    states: Optional[Tuple[FOMCPathState, ...]] = None
    entropy_regularization: float = 1e-4

    @classmethod
    def default_templated_paths(
        cls,
        *,
        current_rate: float,
        cut_size_bps: float = 25.0,
        terminal_move_grid_bps: Sequence[int] = (-100, -75, -50, -25, 0, 25, 50, 75, 100),
        n_plus_years: int = 2,
        max_states: Optional[int] = None,
        entropy_regularization: float = 1e-4,
    ) -> "FOMCPathStateConfig":
        """Build a template config that resolves to a bounded FOMC path library."""
        return cls(
            current_rate=float(current_rate),
            cut_size_bps=float(cut_size_bps),
            terminal_move_grid_bps=tuple(int(x) for x in terminal_move_grid_bps),
            n_plus_years=int(n_plus_years),
            max_states=max_states,
            entropy_regularization=float(entropy_regularization),
        )

    def resolve(
        self,
        *,
        as_of: datetime.date,
        symbols: Sequence[str],
    ) -> Tuple[Tuple[datetime.date, ...], Tuple[FOMCPathState, ...]]:
        """Resolve the concrete meeting grid and path states for a valuation date."""
        from RVUtils.ImpliedDistribution._joint_states import resolve_fomc_path_states

        return resolve_fomc_path_states(self, as_of=as_of, symbols=symbols)


@dataclass(frozen=True)
class JointContractFitDiagnostics:
    """Per-contract diagnostics from the common-state calibration."""

    symbol: str
    rmse_price: float
    max_abs_error_price: float
    residual_std_rate: float
    forward_target: float
    forward_model: float
    forward_error: float
    strike_count: int


@dataclass(frozen=True)
class JointDistributionSnapshot:
    """Common-state joint implied distribution across multiple strip contracts."""

    symbols: List[str]
    as_of: datetime.date
    meeting_dates: Tuple[datetime.date, ...]
    states: Tuple[FOMCPathState, ...]
    state_weights: np.ndarray
    contract_rate_matrix: np.ndarray
    contract_residual_stds: np.ndarray
    rnd_inputs: Dict[str, RNDInput]
    contract_snapshots: Dict[str, ImpliedDistributionSnapshot]
    per_contract_fit: Dict[str, JointContractFitDiagnostics]
    optimization_success: bool
    objective_value: float
    entropy_regularization: float
    fit_message: str
    failure_reason: Optional[str] = None
    provenance: Dict[str, ViewMetadata] = field(default_factory=dict, compare=False)
    state_library: str = "fomc_path_basis"

    @property
    def n_contracts(self) -> int:
        return len(self.symbols)

    @property
    def n_states(self) -> int:
        return len(self.states)

    def symbol_index(self, symbol: str) -> int:
        token = str(symbol).upper()
        if token not in self.symbols:
            raise KeyError(f"{symbol!r} not present in joint snapshot: {self.symbols}")
        return self.symbols.index(token)

    def require_success(self) -> None:
        if not self.optimization_success or self.failure_reason:
            reason = self.failure_reason or self.fit_message or "Joint calibration failed"
            raise ValueError(reason)

    def state_probability_table(self) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import state_probability_table

        return state_probability_table(self)

    def marginal_distribution(self, symbol: str) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import marginal_distribution

        return marginal_distribution(self, symbol=symbol)

    def pair_joint_matrix(self, symbol_x: str, symbol_y: str) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import pair_joint_matrix

        return pair_joint_matrix(self, symbol_x=symbol_x, symbol_y=symbol_y)

    def mean_vector(self) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import mean_vector

        return mean_vector(self)

    def covariance_matrix(self) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import covariance_matrix

        return covariance_matrix(self)

    def correlation_matrix(self) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import correlation_matrix

        return correlation_matrix(self)

    def rank_dependence(self, symbol_x: str, symbol_y: str) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import rank_dependence_summary

        return rank_dependence_summary(self, symbol_x=symbol_x, symbol_y=symbol_y)

    def conditional_distribution(
        self,
        target_symbol: str,
        given_symbol: str,
        *,
        given_values: Optional[Sequence[float]] = None,
        given_range: Optional[Tuple[float, float]] = None,
    ) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import conditional_distribution

        return conditional_distribution(
            self,
            target_symbol=target_symbol,
            given_symbol=given_symbol,
            given_values=given_values,
            given_range=given_range,
        )

    def linear_combination_distribution(self, weights: Dict[str, float]) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import linear_combination_distribution

        return linear_combination_distribution(self, weights=weights)

    def empirical_copula(self, symbol_x: str, symbol_y: str) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import empirical_copula

        return empirical_copula(self, symbol_x=symbol_x, symbol_y=symbol_y)

    def gaussian_copula_summary(self, symbol_x: str, symbol_y: str) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import gaussian_copula_summary

        return gaussian_copula_summary(self, symbol_x=symbol_x, symbol_y=symbol_y)

    def joint_shape_diagnostics(self, symbol_x: str, symbol_y: str) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import joint_shape_diagnostics

        return joint_shape_diagnostics(self, symbol_x=symbol_x, symbol_y=symbol_y)


@dataclass(frozen=True)
class JointDistributionComparison:
    """Date-over-date comparison of two common-state joint distributions."""

    symbols: List[str]
    date_before: datetime.date
    date_after: datetime.date
    snapshot_before: JointDistributionSnapshot
    snapshot_after: JointDistributionSnapshot

    def mean_vector_change(self) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import mean_vector_change

        return mean_vector_change(self)

    def covariance_change(self) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import covariance_change

        return covariance_change(self)

    def correlation_change(self) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import correlation_change

        return correlation_change(self)

    def pair_joint_delta(self, symbol_x: str, symbol_y: str) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import pair_joint_delta_matrix

        return pair_joint_delta_matrix(self, symbol_x=symbol_x, symbol_y=symbol_y)

    def top_pair_cell_changes(self, symbol_x: str, symbol_y: str, *, n: int = 10) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import top_pair_cell_changes

        return top_pair_cell_changes(self, symbol_x=symbol_x, symbol_y=symbol_y, n=n)

    def conditional_change(
        self,
        target_symbol: str,
        given_symbol: str,
        *,
        given_values: Optional[Sequence[float]] = None,
        given_range: Optional[Tuple[float, float]] = None,
    ) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import conditional_distribution_change

        return conditional_distribution_change(
            self,
            target_symbol=target_symbol,
            given_symbol=given_symbol,
            given_values=given_values,
            given_range=given_range,
        )

    def spread_change(self, weights: Dict[str, float]) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import linear_combination_distribution_change

        return linear_combination_distribution_change(self, weights=weights)

    def copula_change_summary(self, symbol_x: str, symbol_y: str) -> AnnotatedResult:
        from RVUtils.ImpliedDistribution._joint_analytics import copula_change_summary

        return copula_change_summary(self, symbol_x=symbol_x, symbol_y=symbol_y)


@dataclass
class FedScenarioConfig:
    """Configurable scenario definitions for Gaussian mixture decomposition.

    Parameters
    ----------
    scenarios : list of ScenarioDefinition
        The scenario definitions (mean rates and optional fixed std devs).
    bin_width_bps : float
        Width of rate bins for BL scenario probabilities.
    scenarios_only : bool
        When True, the distribution is represented solely by the GM scenario
        weights (which sum to 1.0).  BL extraction is skipped, eliminating
        unrealistic tail mass at negative rates that the BL spline can produce.
    """

    scenarios: List[ScenarioDefinition]
    bin_width_bps: float = 25.0
    scenarios_only: bool = False

    @staticmethod
    def default_sofr_scenarios(
        current_rate: float = 4.33,
        cut_size_bps: float = 25.0,
        n_cuts_range: Sequence[int] = (0, 1, 2, 3, 5),
        default_std_bps: Optional[float] = None,
        scenarios_only: bool = False,
    ) -> "FedScenarioConfig":
        """Build standard Fed cut/hike scenarios.

        n_cuts_range: positive = cuts, negative = hikes.
        E.g. [-1, 0, 1, 2, 3, 5, 9] for 1 hike through 9 cuts.
        """
        scenarios: List[ScenarioDefinition] = []
        for n in n_cuts_range:
            mean = current_rate - n * cut_size_bps / 100.0
            if n < 0:
                label = f"{abs(n)} hike{'s' if abs(n) > 1 else ''} ({mean:.2f}%)"
            elif n == 0:
                label = f"Unch ({mean:.2f}%)"
            else:
                label = f"{n} cut{'s' if n > 1 else ''} ({mean:.2f}%)"
            std = default_std_bps / 100.0 if default_std_bps is not None else None
            scenarios.append(ScenarioDefinition(label=label, mean_rate=mean, std_rate=std))
        return FedScenarioConfig(scenarios=scenarios, scenarios_only=scenarios_only)
