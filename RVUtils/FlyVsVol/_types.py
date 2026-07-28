"""Core types for the fly-vs-vol RV framework.

Sign convention (used everywhere in this package):

    fly_bp = (2*f_belly - f_front - f_back) * 100 = D1 - D2
    D1 = f_belly - f_front,  D2 = f_back - f_belly   (positive = hikes priced)

which matches the CME price butterfly (+1/-2/+1) and the Query-layer ``FLY RATE``.
Rates are in percent; every ``*_bp`` quantity is in basis points.

The module is data-agnostic: :meth:`ContractMarginal.from_bl_result` duck-types the
``BreedenLitzenbergerResult`` interface (``strike_grid_rate``, ``rnd_cumulative``,
``input.forward_rate`` plus fit diagnostics) without importing it.

Caveats. All distributions are risk-neutral: persistent gaps between the curve and
options are premium, not free money. The comonotone coupling cannot represent path
reversals (its spread vs the FOMC-path joint measures that premium). SR3 settlement
rates are reference-quarter averages, not Fed target levels. Each marginal is the
distribution at that contract's *option expiry*, so a coupled vector spans different
observation dates; comonotonicity is an assumption on that joint law.
"""
from __future__ import annotations

import dataclasses
import datetime
from typing import Dict, Optional, Tuple

import numpy as np

__all__ = [
    "ContractMarginal",
    "FlyDefinition",
    "FlyVsVolConfig",
    "PathDistribution",
    "FlySnapshot",
    "FLY_WEIGHTS",
]

#: Weights on (front, belly, back) rates producing the fly.
FLY_WEIGHTS: Tuple[float, float, float] = (-1.0, 2.0, -1.0)

_MEAN_GRID_N = 4001


@dataclasses.dataclass(frozen=True)
class ContractMarginal:
    """One contract's risk-neutral marginal as a (rate grid, CDF) pair."""

    symbol: str
    grid_rate: np.ndarray
    cdf: np.ndarray
    forward_rate: float
    as_of: Optional[datetime.date] = None
    forward_residual_bp: float = 0.0
    pre_normalization_mass: float = 1.0
    ghost_mass_fraction: float = 0.0
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        grid = np.asarray(self.grid_rate, dtype=float)
        cdf = np.asarray(self.cdf, dtype=float)
        if grid.ndim != 1 or cdf.ndim != 1 or grid.shape != cdf.shape:
            raise ValueError(
                f"{self.symbol}: grid_rate and cdf must be 1-D arrays of equal length "
                f"(got {grid.shape} vs {cdf.shape})"
            )
        if grid.size < 4:
            raise ValueError(f"{self.symbol}: need at least 4 grid points, got {grid.size}")
        if np.any(np.diff(grid) <= 0):
            raise ValueError(f"{self.symbol}: grid_rate must be strictly ascending")
        if np.any(np.diff(cdf) < -1e-9):
            raise ValueError(f"{self.symbol}: cdf must be non-decreasing")
        object.__setattr__(self, "grid_rate", grid)
        object.__setattr__(self, "cdf", cdf)
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @classmethod
    def from_bl_result(
        cls, symbol: str, bl, *, as_of: Optional[datetime.date] = None
    ) -> "ContractMarginal":
        """Adapt a (duck-typed) BreedenLitzenbergerResult."""
        return cls(
            symbol=symbol,
            grid_rate=np.asarray(bl.strike_grid_rate, dtype=float),
            cdf=np.asarray(bl.rnd_cumulative, dtype=float),
            forward_rate=float(bl.input.forward_rate),
            as_of=as_of,
            forward_residual_bp=float(getattr(bl, "forward_residual_bp", 0.0) or 0.0),
            pre_normalization_mass=float(getattr(bl, "pre_normalization_mass", 1.0) or 1.0),
            ghost_mass_fraction=float(getattr(bl, "ghost_mass_fraction", 0.0) or 0.0),
            warnings=tuple(getattr(bl, "warnings", ()) or ()),
        )

    # -- distribution surface -------------------------------------------------
    def quantile(self, u) -> np.ndarray:
        """Inverse CDF; clamps to the grid ends outside the fitted range."""
        return np.interp(np.asarray(u, dtype=float), self.cdf, self.grid_rate)

    def cdf_at(self, k) -> np.ndarray:
        return np.interp(np.asarray(k, dtype=float), self.grid_rate, self.cdf)

    def percentile(self, p: float) -> float:
        """Quantile with ``p`` in 0..100 (matches BL ``percentile`` semantics)."""
        return float(self.quantile(p / 100.0))

    @property
    def mean(self) -> float:
        # E[X] via integration by parts, treating off-grid mass as edge atoms:
        # E = b*F(b) - a*F(a) - int_a^b F dx + a*F(a) = b*F(b) - trapz(F).
        g, c = self.grid_rate, self.cdf
        total = c[-1]
        if total <= 0:
            return float("nan")
        trapezoid = getattr(np, "trapezoid", np.trapz)
        return float((g[-1] * c[-1] - trapezoid(c, g)) / total)

    @property
    def median(self) -> float:
        return self.percentile(50)

    @property
    def mode(self) -> float:
        d = np.diff(self.cdf) / np.diff(self.grid_rate)
        i = int(np.argmax(d))
        return float(0.5 * (self.grid_rate[i] + self.grid_rate[i + 1]))


@dataclasses.dataclass(frozen=True)
class FlyDefinition:
    """An adjacent-quarterly (or any) three-contract butterfly."""

    front: str
    belly: str
    back: str

    @property
    def label(self) -> str:
        return f"{self.front}-{self.belly}-{self.back}"

    @property
    def symbols(self) -> Tuple[str, str, str]:
        return (self.front, self.belly, self.back)


@dataclasses.dataclass(frozen=True)
class FlyVsVolConfig:
    move_size_bp: float = 25.0
    n_quantiles: int = 20001
    n_copula_sims: int = 200_000
    copula_seed: int = 7
    tail_lo: float = 0.15
    tail_hi: float = 0.85
    max_abs_forward_residual_bp: float = 2.5
    max_pre_normalization_mass: float = 1.02
    max_ghost_mass_fraction: float = 0.02
    zscore_window: int = 120
    zscore_min_periods: int = 40


@dataclasses.dataclass(frozen=True)
class PathDistribution:
    """Distribution of the fly settlement ``phi`` under one coupling."""

    e_phi_bp: float
    phi_median_bp: float
    p_phi_gt0: float
    phi_quantiles_bp: Dict[int, float]
    e_d1_bp: float
    e_d2_bp: float
    e_n1: float
    e_n2: float
    prob_delta: float
    p_dn_pos: float
    p_dn_neg: float
    p_dn_zero: float
    dn_table: Dict[int, float]
    e_phi_given_dn_bp: Dict[int, float]
    tail_slope_upper: float
    tail_slope_lower: float


@dataclasses.dataclass(frozen=True)
class FlySnapshot:
    """All fly-vs-vol metrics for one triple on one date."""

    fly: FlyDefinition
    as_of: Optional[datetime.date]
    forwards: Tuple[float, float, float]
    spread1_bp: float
    spread2_bp: float
    fly_bp: float
    fly_mean_bp: float
    fly_median_path_bp: float
    fly_mode_path_bp: float
    tail_rent_bp: float
    heuristic_prob: float
    comonotone: PathDistribution
    copula: Optional[PathDistribution]
    quality_ok: bool
    quality_flags: Tuple[str, ...]
    legs: Tuple[ContractMarginal, ContractMarginal, ContractMarginal]

    @property
    def heuristic_gap(self) -> float:
        return self.heuristic_prob - self.comonotone.prob_delta

    def to_row(self) -> Dict[str, object]:
        c = self.comonotone
        return {
            "label": self.fly.label,
            "as_of": self.as_of,
            "fly_bp": self.fly_bp,
            "spread1_bp": self.spread1_bp,
            "spread2_bp": self.spread2_bp,
            "fly_mean_bp": self.fly_mean_bp,
            "fly_median_path_bp": self.fly_median_path_bp,
            "tail_rent_bp": self.tail_rent_bp,
            "heuristic_prob": self.heuristic_prob,
            "prob_delta": c.prob_delta,
            "heuristic_gap": self.heuristic_gap,
            "p_dn_zero": c.p_dn_zero,
            "p_dn_pos": c.p_dn_pos,
            "phi_p05": c.phi_quantiles_bp[5],
            "phi_p95": c.phi_quantiles_bp[95],
            "phi_iqr_bp": c.phi_quantiles_bp[75] - c.phi_quantiles_bp[25],
            "p_phi_gt0": c.p_phi_gt0,
            "tail_slope_upper": c.tail_slope_upper,
            "tail_slope_lower": c.tail_slope_lower,
            "quality_ok": self.quality_ok,
            "n_flags": len(self.quality_flags),
        }
