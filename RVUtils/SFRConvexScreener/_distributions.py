"""Per-contract BL marginals + structure payoff PDFs under three joint
assumptions (common-state, historical Gaussian copula, perfect correlation).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

from RVUtils.ImpliedDistribution import (
    BreedenLitzenbergerResult,
    FedScenarioConfig,
    ImpliedDistributionSnapshot,
    JointDistributionSnapshot,
    SFRImpliedDistribution,
)
from RVUtils.SFRConvexScreener._types import Leg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PerContractDistribution:
    symbol: str
    bl: BreedenLitzenbergerResult

    @property
    def rate_grid(self) -> np.ndarray:
        return self.bl.strike_grid_rate

    @property
    def density(self) -> np.ndarray:
        return self.bl.rnd_density


def extract_bl_marginals(
    smiles: Mapping[str, Any],
    *,
    dist_extractor: Optional[Any] = None,
    scenario_config: Optional[FedScenarioConfig] = None,
    jpm_method: bool = False,
) -> Dict[str, PerContractDistribution]:
    """Run BL extraction on each smile. Fail-soft per contract.

    Parameters
    ----------
    jpm_method : bool
        When True, follow JPM Tech Appendix A more strictly: use raw market
        vols (no SABR fit, no SABR-grid extrapolation), 4th-order spline on
        observed strikes plus linear ghost points, smoothing parameter 1e-4,
        25bp bins. Default False keeps the SABR + ghost-points hybrid that
        ARBS has used historically (smoother tails at the cost of leaning
        on the SABR β/ρ/ν parameters).
    """
    if dist_extractor is None:
        scenarios = scenario_config or FedScenarioConfig.default_sofr_scenarios()
        if jpm_method:
            dist_extractor = SFRImpliedDistribution(
                scenario_config=scenarios,
                use_sabr_vols=False,
                sabr_extrapolation=False,
                # Per Appendix A: 4th-order spline, smoothing 1e-4,
                # 10 ghost points, 25bp bins. These are already the
                # ARBS defaults — we just disable the SABR resampling.
                smoothing_param=1e-4,
                spline_order=4,
                n_ghost_points=10,
                bin_width_bps=25.0,
            )
        else:
            dist_extractor = SFRImpliedDistribution(scenario_config=scenarios)

    out: Dict[str, PerContractDistribution] = {}
    for symbol, smile in smiles.items():
        try:
            snap: ImpliedDistributionSnapshot = dist_extractor.extract(smile)
        except Exception as exc:  # noqa: BLE001
            logger.warning("BL extraction failed for %s: %s", symbol, exc)
            continue
        if snap.bl_result is None:
            logger.warning("no BL result for %s", symbol)
            continue
        out[symbol] = PerContractDistribution(symbol=symbol, bl=snap.bl_result)
    return out


def payoff_pdf_common_state(
    legs: Sequence[Leg],
    *,
    joint: JointDistributionSnapshot,
) -> Tuple[np.ndarray, np.ndarray]:
    """Common-state structure payoff PDF: weighted linear-combination of
    contract rates over the calibrated FOMC-path joint snapshot.

    Returns
    -------
    outcomes_bp : np.ndarray
        Linear-combination outcomes converted to basis points.
    probs : np.ndarray
        Discrete probabilities summing to 1.
    """
    weights = {leg.contract: float(leg.weight) for leg in legs}
    annotated = joint.linear_combination_distribution(weights)
    df: pd.DataFrame = annotated.data
    # `_group_distribution` names the value column either "value" or
    # "linear_combination" depending on the caller — accept either.
    if "value" in df.columns:
        value_col = "value"
    elif "linear_combination" in df.columns:
        value_col = "linear_combination"
    else:
        non_prob = [c for c in df.columns if c != "probability"]
        if not non_prob:
            raise KeyError(
                f"linear_combination_distribution returned unexpected columns {list(df.columns)}"
            )
        value_col = non_prob[0]
    outcomes_pct = np.asarray(df[value_col], dtype=float)
    probs = np.asarray(df["probability"], dtype=float)
    if probs.sum() > 0:
        probs = probs / probs.sum()
    outcomes_bp = outcomes_pct * 100.0
    return outcomes_bp, probs


def _inverse_marginal_cdf(bl: BreedenLitzenbergerResult, u: np.ndarray) -> np.ndarray:
    """Vectorized inverse-CDF lookup on the BL grid."""
    return np.interp(u, bl.rnd_cumulative, bl.strike_grid_rate)


def payoff_pdf_historical_gaussian_copula(
    legs: Sequence[Leg],
    *,
    marginals: Mapping[str, PerContractDistribution],
    corr_matrix: pd.DataFrame,
    n_sim: int = 100_000,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """Sample structure payoffs in basis points via a Gaussian copula on
    historical correlations and BL marginals.

    Returns
    -------
    samples_bp : np.ndarray of shape (n_sim,)
        P&L of the structure relative to its current level (bp).
    """
    rng = rng or np.random.default_rng()
    contracts = [leg.contract for leg in legs]
    weights = np.array([leg.weight for leg in legs], dtype=float)

    sub = corr_matrix.reindex(index=contracts, columns=contracts).to_numpy(dtype=float)
    if not np.all(np.isfinite(sub)):
        sub = np.eye(len(contracts))
    sub = (sub + sub.T) / 2.0
    eig, vec = np.linalg.eigh(sub)
    eig = np.clip(eig, 1e-8, None)
    L = vec @ np.diag(np.sqrt(eig))

    z = rng.standard_normal(size=(n_sim, len(contracts))) @ L.T
    u = norm.cdf(z)
    rates_pct = np.empty_like(u)
    for i, contract in enumerate(contracts):
        rates_pct[:, i] = _inverse_marginal_cdf(marginals[contract].bl, u[:, i])

    payoff_pct = rates_pct @ weights
    current_pct = np.array(
        [marginals[c].bl.input.forward_rate for c in contracts]
    ) @ weights
    return (payoff_pct - current_pct) * 100.0


def payoff_pdf_perfect_correlation(
    legs: Sequence[Leg],
    *,
    marginals: Mapping[str, PerContractDistribution],
) -> Tuple[np.ndarray, np.ndarray]:
    """Phase-1 baseline: assume all legs move by the same shift, weight by the
    front contract's marginal."""
    front_bl = marginals[legs[0].contract].bl
    shifts_pct = front_bl.strike_grid_rate - front_bl.input.forward_rate
    sum_weights = sum(leg.weight for leg in legs)
    payoff_bp = shifts_pct * sum_weights * 100.0

    density = front_bl.rnd_density.copy()
    grid = front_bl.strike_grid_rate
    dx = np.diff(grid)
    probs = np.zeros_like(density)
    if len(dx) > 0:
        probs[:-1] = 0.5 * (density[:-1] + density[1:]) * dx
        probs[-1] = probs[-2] if len(probs) > 1 else 1.0
    total = probs.sum()
    if total > 0:
        probs = probs / total
    return payoff_bp, probs


def payoff_pdf_outright(
    leg: Leg,
    *,
    marginals: Mapping[str, PerContractDistribution],
) -> Tuple[np.ndarray, np.ndarray]:
    """Single-contract directional payoff PDF.

    Returns the BL marginal centred at the contract forward — outcomes in bp
    relative to forward, weighted by the contract's RN density. With
    ``leg.weight = +1`` the resulting distribution is the realised rate
    change in bp; ``leg.weight = -1`` flips the sign (long-price /
    receiver convention).
    """
    bl = marginals[leg.contract].bl
    grid = bl.strike_grid_rate
    payoff_bp = (grid - bl.input.forward_rate) * float(leg.weight) * 100.0
    density = bl.rnd_density.copy()
    dx = np.diff(grid)
    probs = np.zeros_like(density)
    if len(dx) > 0:
        probs[:-1] = 0.5 * (density[:-1] + density[1:]) * dx
        probs[-1] = probs[-2] if len(probs) > 1 else 1.0
    total = probs.sum()
    if total > 0:
        probs = probs / total
    # Sort by payoff so downstream metrics (CDF interpolation) work for
    # both leg.weight = +1 and -1.
    order = np.argsort(payoff_bp)
    return payoff_bp[order], probs[order]
