import datetime
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union

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

    def percentile(self, p: float) -> float:
        """Return the rate at the p-th percentile (0-100)."""
        idx = np.searchsorted(self.rnd_cumulative, p / 100.0)
        idx = min(idx, len(self.strike_grid_rate) - 1)
        return float(self.strike_grid_rate[idx])


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

    def scenario_weight_dict(self) -> Dict[str, float]:
        return {s.label: float(w) for s, w in zip(self.scenarios, self.weights)}


@dataclass(frozen=True)
class ImpliedDistributionSnapshot:
    """Combined result for a single contract/date."""

    symbol: str
    as_of: datetime.date
    bl_result: Optional[BreedenLitzenbergerResult]
    gm_result: Optional[GaussianMixtureResult]


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


@dataclass
class FedScenarioConfig:
    """Configurable scenario definitions for Gaussian mixture decomposition."""

    scenarios: List[ScenarioDefinition]
    bin_width_bps: float = 25.0

    @staticmethod
    def default_sofr_scenarios(
        current_rate: float = 4.33,
        cut_size_bps: float = 25.0,
        n_cuts_range: Sequence[int] = (0, 1, 2, 3, 5),
        default_std_bps: Optional[float] = None,
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
        return FedScenarioConfig(scenarios=scenarios)
