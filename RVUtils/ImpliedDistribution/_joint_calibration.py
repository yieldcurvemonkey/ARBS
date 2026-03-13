"""Joint calibration of a shared common-state strip distribution."""

from __future__ import annotations

import math
from typing import Dict, Sequence

import numpy as np
from scipy.optimize import linprog, minimize

from RVUtils.ImpliedDistribution._bachelier import bachelier_call_prices_vectorized
from RVUtils.ImpliedDistribution._joint_states import contract_rate_matrix
from RVUtils.ImpliedDistribution._types import (
    JointContractFitDiagnostics,
    JointDistributionSnapshot,
    RNDInput,
    ViewMetadata,
)


def _joint_mixture_call_prices(
    strikes: np.ndarray,
    *,
    tte: float,
    discount: float,
    mean_rates: np.ndarray,
    residual_std_rate: float,
    weights: np.ndarray,
) -> np.ndarray:
    prices = np.zeros(len(strikes), dtype=float)
    vols = np.full(len(strikes), float(residual_std_rate), dtype=float)
    for rate_mean, weight in zip(mean_rates, weights):
        if weight <= 0:
            continue
        prices += float(weight) * bachelier_call_prices_vectorized(
            strikes,
            100.0 - float(rate_mean),
            vols,
            tte,
            discount,
        )
    return prices


def _default_provenance() -> Dict[str, ViewMetadata]:
    return {
        "state_probability_table": ViewMetadata(
            "calibrated common-state exact within basis",
            note="model-imposed FOMC path basis",
        ),
        "pair_joint_matrix": ViewMetadata(
            "calibrated common-state exact within basis",
            note="exact discrete aggregation of shared-state weights",
        ),
        "marginal_distribution": ViewMetadata(
            "exact aggregation",
            note="collapsed from calibrated common-state weights",
        ),
        "moments": ViewMetadata(
            "exact aggregation",
            note="computed from calibrated common-state weights",
        ),
        "conditional_distribution": ViewMetadata(
            "exact aggregation",
            note="conditioning over discrete shared states",
        ),
        "linear_combination_distribution": ViewMetadata(
            "exact aggregation",
            note="deterministic transform of common-state outcomes",
        ),
        "empirical_copula": ViewMetadata(
            "calibrated common-state exact within basis",
            note="weighted midrank copula on discrete shared states",
        ),
        "gaussian_copula_summary": ViewMetadata(
            "smoothed or fitted approximation",
            note="fitted Gaussian copula summary",
        ),
        "joint_shape_diagnostics": ViewMetadata(
            "calibrated common-state exact within basis",
            note="heuristics on the discrete shared-state joint",
        ),
        "joint_contour": ViewMetadata(
            "smoothed or fitted approximation",
            note="smoothed view of the discrete joint matrix",
        ),
        "direct_market_input": ViewMetadata(
            "direct market input",
            note="listed strike option prices / standalone marginals",
        ),
    }


def _build_failure_snapshot(
    *,
    symbols: Sequence[str],
    as_of,
    meeting_dates,
    states,
    rate_matrix,
    rnd_inputs_by_symbol,
    contract_snapshots,
    initial_sigmas,
    message: str,
    failure_reason: str,
) -> JointDistributionSnapshot:
    per_contract = {
        sym: JointContractFitDiagnostics(
            symbol=sym,
            rmse_price=float("nan"),
            max_abs_error_price=float("nan"),
            residual_std_rate=float(initial_sigmas[idx]),
            forward_target=float(rnd_inputs_by_symbol[sym].forward_rate),
            forward_model=float("nan"),
            forward_error=float("nan"),
            strike_count=int(len(rnd_inputs_by_symbol[sym].strikes_price)),
        )
        for idx, sym in enumerate(symbols)
    }
    return JointDistributionSnapshot(
        symbols=list(symbols),
        as_of=as_of,
        meeting_dates=tuple(meeting_dates),
        states=tuple(states),
        state_weights=np.zeros(len(states), dtype=float),
        contract_rate_matrix=np.asarray(rate_matrix, dtype=float),
        contract_residual_stds=np.asarray(initial_sigmas, dtype=float),
        rnd_inputs=dict(rnd_inputs_by_symbol),
        contract_snapshots=dict(contract_snapshots),
        per_contract_fit=per_contract,
        optimization_success=False,
        objective_value=float("nan"),
        entropy_regularization=0.0,
        fit_message=message,
        failure_reason=failure_reason,
        provenance=_default_provenance(),
    )


def calibrate_joint_distribution(
    rnd_inputs_by_symbol: Dict[str, RNDInput],
    *,
    contract_snapshots,
    state_config,
    optimize_stds: bool,
    initial_std_bps: float,
) -> JointDistributionSnapshot:
    """Fit a shared common-state distribution to multiple contract smiles."""
    if not rnd_inputs_by_symbol:
        raise ValueError("rnd_inputs_by_symbol must not be empty")

    symbols = [str(sym).upper() for sym in rnd_inputs_by_symbol.keys()]
    as_of_values = {rnd.as_of for rnd in rnd_inputs_by_symbol.values()}
    if len(as_of_values) != 1:
        raise ValueError("All smiles in extract_joint() must share the same as_of date")
    as_of = next(iter(as_of_values))

    meeting_dates, states = state_config.resolve(as_of=as_of, symbols=symbols)
    if not states:
        return _build_failure_snapshot(
            symbols=symbols,
            as_of=as_of,
            meeting_dates=meeting_dates,
            states=states,
            rate_matrix=np.zeros((0, len(symbols))),
            rnd_inputs_by_symbol=rnd_inputs_by_symbol,
            contract_snapshots=contract_snapshots,
            initial_sigmas=np.full(len(symbols), float(initial_std_bps) / 100.0),
            message="No common states were generated",
            failure_reason="No common states available for joint calibration",
        )

    rate_matrix, _ = contract_rate_matrix(states, symbols=symbols)
    n_states = len(states)
    n_contracts = len(symbols)

    initial_sigmas = np.full(n_contracts, float(initial_std_bps) / 100.0, dtype=float)
    forward_targets = np.array([rnd_inputs_by_symbol[sym].forward_rate for sym in symbols], dtype=float)

    feasibility_a = np.vstack([np.ones(n_states, dtype=float), rate_matrix.T])
    feasibility_b = np.concatenate([[1.0], forward_targets])
    feasible = linprog(
        c=np.zeros(n_states, dtype=float),
        A_eq=feasibility_a,
        b_eq=feasibility_b,
        bounds=[(0.0, 1.0)] * n_states,
        method="highs",
    )
    if not feasible.success or feasible.x is None:
        reason = feasible.message or "Forward vector is outside the convex hull of the common-state basis"
        return _build_failure_snapshot(
            symbols=symbols,
            as_of=as_of,
            meeting_dates=meeting_dates,
            states=states,
            rate_matrix=rate_matrix,
            rnd_inputs_by_symbol=rnd_inputs_by_symbol,
            contract_snapshots=contract_snapshots,
            initial_sigmas=initial_sigmas,
            message=str(reason),
            failure_reason="Shared-state forward recovery is infeasible for the selected basis",
        )

    prior = np.full(n_states, 1.0 / n_states, dtype=float)
    entropy_lambda = float(state_config.entropy_regularization)

    if optimize_stds:
        x0 = np.concatenate([feasible.x, initial_sigmas])
        bounds = [(0.0, 1.0)] * n_states + [(0.001, 2.0)] * n_contracts
    else:
        x0 = feasible.x.copy()
        bounds = [(0.0, 1.0)] * n_states

    def _unpack(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        weights = np.asarray(x[:n_states], dtype=float)
        sigmas = np.asarray(x[n_states:], dtype=float) if optimize_stds else initial_sigmas
        return weights, sigmas

    def _objective(x: np.ndarray) -> float:
        weights, sigmas = _unpack(x)
        if np.any(weights < -1e-10) or np.any(sigmas <= 0):
            return 1e18
        sse = 0.0
        for idx, sym in enumerate(symbols):
            rnd = rnd_inputs_by_symbol[sym]
            model = _joint_mixture_call_prices(
                rnd.strikes_price,
                tte=rnd.time_to_expiry,
                discount=rnd.discount_factor,
                mean_rates=rate_matrix[:, idx],
                residual_std_rate=float(sigmas[idx]),
                weights=weights,
            )
            diff = model - rnd.call_premiums
            sse += float(np.dot(diff, diff))
        if entropy_lambda > 0:
            safe = np.clip(weights, 1e-12, 1.0)
            sse += entropy_lambda * float(np.sum(safe * np.log(safe / prior)))
        return sse

    constraints = [{"type": "eq", "fun": lambda x: float(np.sum(_unpack(x)[0]) - 1.0)}]
    for contract_idx in range(n_contracts):
        constraints.append(
            {
                "type": "eq",
                "fun": lambda x, idx=contract_idx: float(np.dot(_unpack(x)[0], rate_matrix[:, idx]) - forward_targets[idx]),
            }
        )

    result = minimize(
        _objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 2000, "ftol": 1e-12},
    )

    raw_weights, sigmas = _unpack(result.x if result.x is not None else x0)
    weights = np.maximum(raw_weights, 0.0)
    if weights.sum() > 0:
        weights = weights / weights.sum()

    forward_model = rate_matrix.T @ weights if n_states else np.full(n_contracts, float("nan"))
    fit_ok = bool(result.success)
    fit_message = str(result.message) if hasattr(result, "message") else ""
    failure_reason = None
    if np.any(np.abs(forward_model - forward_targets) > 5e-4):
        fit_ok = False
        failure_reason = "Optimized weights do not satisfy forward recovery within tolerance"
    if np.any(weights < -1e-8) or not math.isclose(float(weights.sum()), 1.0, rel_tol=1e-6, abs_tol=1e-6):
        fit_ok = False
        failure_reason = failure_reason or "Optimized weights are not a valid probability vector"

    per_contract = {}
    for idx, sym in enumerate(symbols):
        rnd = rnd_inputs_by_symbol[sym]
        model = _joint_mixture_call_prices(
            rnd.strikes_price,
            tte=rnd.time_to_expiry,
            discount=rnd.discount_factor,
            mean_rates=rate_matrix[:, idx],
            residual_std_rate=float(sigmas[idx]),
            weights=weights,
        )
        diff = model - rnd.call_premiums
        rmse = float(np.sqrt(np.mean(diff**2)))
        max_err = float(np.max(np.abs(diff)))
        per_contract[sym] = JointContractFitDiagnostics(
            symbol=sym,
            rmse_price=rmse,
            max_abs_error_price=max_err,
            residual_std_rate=float(sigmas[idx]),
            forward_target=float(forward_targets[idx]),
            forward_model=float(forward_model[idx]),
            forward_error=float(forward_model[idx] - forward_targets[idx]),
            strike_count=int(len(rnd.strikes_price)),
        )

    return JointDistributionSnapshot(
        symbols=list(symbols),
        as_of=as_of,
        meeting_dates=tuple(meeting_dates),
        states=tuple(states),
        state_weights=np.asarray(weights, dtype=float),
        contract_rate_matrix=np.asarray(rate_matrix, dtype=float),
        contract_residual_stds=np.asarray(sigmas, dtype=float),
        rnd_inputs=dict(rnd_inputs_by_symbol),
        contract_snapshots=dict(contract_snapshots),
        per_contract_fit=per_contract,
        optimization_success=fit_ok,
        objective_value=float(result.fun) if hasattr(result, "fun") else float("nan"),
        entropy_regularization=entropy_lambda,
        fit_message=fit_message,
        failure_reason=failure_reason,
        provenance=_default_provenance(),
    )
