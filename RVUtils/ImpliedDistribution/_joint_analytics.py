"""Exact analytics derived from a calibrated common-state strip distribution."""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

from RVUtils.ImpliedDistribution._types import AnnotatedResult, JointDistributionComparison, JointDistributionSnapshot, ViewMetadata


_GROUP_DECIMALS = 10


def _metadata(snapshot: JointDistributionSnapshot, key: str, fallback_note: str) -> ViewMetadata:
    return snapshot.provenance.get(key, ViewMetadata(key.replace("_", " "), note=fallback_note))


def _comparison_metadata(support: str, note: str) -> ViewMetadata:
    return ViewMetadata(support, note=note)


def _group_distribution(values: np.ndarray, weights: np.ndarray, *, value_name: str = "value") -> pd.DataFrame:
    rounded = np.round(np.asarray(values, dtype=float), _GROUP_DECIMALS)
    df = pd.DataFrame({value_name: rounded, "probability": np.asarray(weights, dtype=float)})
    grouped = df.groupby(value_name, as_index=False, sort=True)["probability"].sum()
    grouped = grouped.sort_values(value_name).reset_index(drop=True)
    return grouped


def _weighted_mean(matrix: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return np.sum(matrix * weights[:, None], axis=0)


def _weighted_covariance(matrix: np.ndarray, weights: np.ndarray) -> np.ndarray:
    mean = _weighted_mean(matrix, weights)
    centered = matrix - mean
    return centered.T @ (centered * weights[:, None])


def _weighted_corr_from_values(x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> float:
    if np.sum(weights) <= 0:
        return float("nan")
    weights = weights / np.sum(weights)
    x_mean = float(np.sum(x * weights))
    y_mean = float(np.sum(y * weights))
    x_var = float(np.sum((x - x_mean) ** 2 * weights))
    y_var = float(np.sum((y - y_mean) ** 2 * weights))
    if x_var <= 0 or y_var <= 0:
        return 0.0
    cov = float(np.sum((x - x_mean) * (y - y_mean) * weights))
    return cov / math.sqrt(x_var * y_var)


def _weighted_midranks(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    rounded = np.round(np.asarray(values, dtype=float), _GROUP_DECIMALS)
    order = np.argsort(rounded, kind="mergesort")
    sorted_values = rounded[order]
    sorted_weights = np.asarray(weights, dtype=float)[order]

    ranks_sorted = np.zeros(len(sorted_values), dtype=float)
    cumulative = 0.0
    i = 0
    while i < len(sorted_values):
        j = i + 1
        while j < len(sorted_values) and sorted_values[j] == sorted_values[i]:
            j += 1
        group_weight = float(np.sum(sorted_weights[i:j]))
        midrank = cumulative + 0.5 * group_weight
        ranks_sorted[i:j] = midrank
        cumulative += group_weight
        i = j

    ranks = np.zeros_like(ranks_sorted)
    ranks[order] = ranks_sorted
    total = max(float(np.sum(weights)), 1e-12)
    return ranks / total


def _weighted_kendall_tau_b(x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> float:
    x_rounded = np.round(np.asarray(x, dtype=float), _GROUP_DECIMALS)
    y_rounded = np.round(np.asarray(y, dtype=float), _GROUP_DECIMALS)
    weights = np.asarray(weights, dtype=float)
    concordant = 0.0
    discordant = 0.0
    ties_x = 0.0
    ties_y = 0.0
    n = len(x_rounded)
    for i in range(n):
        for j in range(i + 1, n):
            pair_weight = float(weights[i] * weights[j])
            if pair_weight <= 0:
                continue
            dx = x_rounded[i] - x_rounded[j]
            dy = y_rounded[i] - y_rounded[j]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                ties_x += pair_weight
            elif dy == 0:
                ties_y += pair_weight
            elif dx * dy > 0:
                concordant += pair_weight
            else:
                discordant += pair_weight
    denom = math.sqrt(max(concordant + discordant + ties_x, 0.0) * max(concordant + discordant + ties_y, 0.0))
    if denom <= 0:
        return 0.0
    return float((concordant - discordant) / denom)


def _joint_matrix_dataframe(snapshot: JointDistributionSnapshot, *, symbol_x: str, symbol_y: str) -> pd.DataFrame:
    x_idx = snapshot.symbol_index(symbol_x)
    y_idx = snapshot.symbol_index(symbol_y)
    df = pd.DataFrame(
        {
            str(symbol_x).upper(): np.round(snapshot.contract_rate_matrix[:, x_idx], _GROUP_DECIMALS),
            str(symbol_y).upper(): np.round(snapshot.contract_rate_matrix[:, y_idx], _GROUP_DECIMALS),
            "probability": snapshot.state_weights,
        }
    )
    pivot = pd.pivot_table(
        df,
        values="probability",
        index=str(symbol_x).upper(),
        columns=str(symbol_y).upper(),
        aggfunc="sum",
        fill_value=0.0,
        sort=True,
    )
    pivot = pivot.sort_index().sort_index(axis=1)
    pivot.index.name = str(symbol_x).upper()
    pivot.columns.name = str(symbol_y).upper()
    return pivot


def _align_series(before: pd.Series, after: pd.Series) -> pd.DataFrame:
    frame = pd.concat([before.rename("before"), after.rename("after")], axis=1).fillna(0.0)
    frame["delta"] = frame["after"] - frame["before"]
    return frame


def _js_divergence(p: np.ndarray, q: np.ndarray) -> float:
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float)
    if p.sum() > 0:
        p = p / p.sum()
    if q.sum() > 0:
        q = q / q.sum()
    m = 0.5 * (p + q)

    def _kl(a: np.ndarray, b: np.ndarray) -> float:
        mask = (a > 0) & (b > 0)
        if not np.any(mask):
            return 0.0
        return float(np.sum(a[mask] * np.log(a[mask] / b[mask])))

    return 0.5 * (_kl(p, m) + _kl(q, m))


def state_probability_table(snapshot: JointDistributionSnapshot) -> AnnotatedResult:
    snapshot.require_success()
    rows = []
    for idx, state in enumerate(snapshot.states):
        row = {
            "state_index": idx,
            "state_label": state.label,
            "probability": float(snapshot.state_weights[idx]),
            "terminal_rate": float(state.terminal_rate),
        }
        for sym_idx, sym in enumerate(snapshot.symbols):
            row[sym] = float(snapshot.contract_rate_matrix[idx, sym_idx])
        rows.append(row)
    df = pd.DataFrame(rows).sort_values("probability", ascending=False).reset_index(drop=True)
    return AnnotatedResult(df, _metadata(snapshot, "state_probability_table", "common-state probability table"))


def marginal_distribution(snapshot: JointDistributionSnapshot, *, symbol: str) -> AnnotatedResult:
    snapshot.require_success()
    idx = snapshot.symbol_index(symbol)
    df = _group_distribution(snapshot.contract_rate_matrix[:, idx], snapshot.state_weights, value_name=str(symbol).upper())
    return AnnotatedResult(df, _metadata(snapshot, "marginal_distribution", "marginal implied by the joint"))


def pair_joint_matrix(snapshot: JointDistributionSnapshot, *, symbol_x: str, symbol_y: str) -> AnnotatedResult:
    snapshot.require_success()
    return AnnotatedResult(
        _joint_matrix_dataframe(snapshot, symbol_x=symbol_x, symbol_y=symbol_y),
        _metadata(snapshot, "pair_joint_matrix", "pairwise joint matrix"),
    )


def mean_vector(snapshot: JointDistributionSnapshot) -> AnnotatedResult:
    snapshot.require_success()
    series = pd.Series(_weighted_mean(snapshot.contract_rate_matrix, snapshot.state_weights), index=snapshot.symbols, name="mean_rate")
    return AnnotatedResult(series, _metadata(snapshot, "moments", "mean vector"))


def covariance_matrix(snapshot: JointDistributionSnapshot) -> AnnotatedResult:
    snapshot.require_success()
    cov = _weighted_covariance(snapshot.contract_rate_matrix, snapshot.state_weights)
    df = pd.DataFrame(cov, index=snapshot.symbols, columns=snapshot.symbols)
    return AnnotatedResult(df, _metadata(snapshot, "moments", "covariance matrix"))


def correlation_matrix(snapshot: JointDistributionSnapshot) -> AnnotatedResult:
    snapshot.require_success()
    cov = _weighted_covariance(snapshot.contract_rate_matrix, snapshot.state_weights)
    vol = np.sqrt(np.clip(np.diag(cov), a_min=0.0, a_max=None))
    denom = np.outer(vol, vol)
    corr = np.divide(cov, denom, out=np.zeros_like(cov), where=denom > 0)
    df = pd.DataFrame(corr, index=snapshot.symbols, columns=snapshot.symbols)
    return AnnotatedResult(df, _metadata(snapshot, "moments", "correlation matrix"))


def rank_dependence_summary(snapshot: JointDistributionSnapshot, *, symbol_x: str, symbol_y: str) -> AnnotatedResult:
    snapshot.require_success()
    x_idx = snapshot.symbol_index(symbol_x)
    y_idx = snapshot.symbol_index(symbol_y)
    x = snapshot.contract_rate_matrix[:, x_idx]
    y = snapshot.contract_rate_matrix[:, y_idx]
    weights = snapshot.state_weights
    u = _weighted_midranks(x, weights)
    v = _weighted_midranks(y, weights)
    series = pd.Series(
        {
            "spearman": _weighted_corr_from_values(u, v, weights),
            "kendall_tau_b": _weighted_kendall_tau_b(x, y, weights),
        },
        name=f"{str(symbol_x).upper()}__{str(symbol_y).upper()}",
    )
    return AnnotatedResult(series, _metadata(snapshot, "moments", "rank dependence summary"))


def conditional_distribution(
    snapshot: JointDistributionSnapshot,
    *,
    target_symbol: str,
    given_symbol: str,
    given_values: Optional[Sequence[float]] = None,
    given_range: Optional[Tuple[float, float]] = None,
) -> AnnotatedResult:
    snapshot.require_success()
    if (given_values is None) == (given_range is None):
        raise ValueError("Specify exactly one of given_values or given_range")

    given_idx = snapshot.symbol_index(given_symbol)
    target_idx = snapshot.symbol_index(target_symbol)
    given_data = np.round(snapshot.contract_rate_matrix[:, given_idx], _GROUP_DECIMALS)
    if given_values is not None:
        target_values = {round(float(v), _GROUP_DECIMALS) for v in given_values}
        mask = np.array([val in target_values for val in given_data], dtype=bool)
        selector = {"mode": "values", "values": sorted(target_values)}
    else:
        lo, hi = given_range or (float("nan"), float("nan"))
        mask = (given_data >= float(lo)) & (given_data <= float(hi))
        selector = {"mode": "range", "range": (float(lo), float(hi))}

    selected_weights = snapshot.state_weights[mask]
    conditioning_mass = float(np.sum(selected_weights))
    if conditioning_mass <= 0:
        raise ValueError("Condition selects zero probability mass")
    target_values = snapshot.contract_rate_matrix[:, target_idx][mask]
    distribution = _group_distribution(target_values, selected_weights / conditioning_mass, value_name=str(target_symbol).upper())
    payload = {
        "distribution": distribution,
        "conditioning_probability": conditioning_mass,
        "selector": selector,
    }
    return AnnotatedResult(payload, _metadata(snapshot, "conditional_distribution", "conditional distribution"))


def linear_combination_distribution(snapshot: JointDistributionSnapshot, *, weights: Dict[str, float]) -> AnnotatedResult:
    snapshot.require_success()
    if not weights:
        raise ValueError("weights must not be empty")
    weight_vector = np.zeros(snapshot.n_contracts, dtype=float)
    for symbol, coeff in weights.items():
        weight_vector[snapshot.symbol_index(symbol)] = float(coeff)
    values = snapshot.contract_rate_matrix @ weight_vector
    df = _group_distribution(values, snapshot.state_weights, value_name="linear_combination")
    return AnnotatedResult(df, _metadata(snapshot, "linear_combination_distribution", "linear-combination distribution"))


def empirical_copula(snapshot: JointDistributionSnapshot, *, symbol_x: str, symbol_y: str) -> AnnotatedResult:
    snapshot.require_success()
    x_idx = snapshot.symbol_index(symbol_x)
    y_idx = snapshot.symbol_index(symbol_y)
    x = snapshot.contract_rate_matrix[:, x_idx]
    y = snapshot.contract_rate_matrix[:, y_idx]
    weights = snapshot.state_weights
    df = pd.DataFrame(
        {
            "state_index": np.arange(snapshot.n_states, dtype=int),
            "state_label": [state.label for state in snapshot.states],
            "x_value": x,
            "y_value": y,
            "u": _weighted_midranks(x, weights),
            "v": _weighted_midranks(y, weights),
            "weight": weights,
        }
    )
    return AnnotatedResult(df, _metadata(snapshot, "empirical_copula", "empirical copula"))


def gaussian_copula_summary(snapshot: JointDistributionSnapshot, *, symbol_x: str, symbol_y: str) -> AnnotatedResult:
    snapshot.require_success()
    copula_df = empirical_copula(snapshot, symbol_x=symbol_x, symbol_y=symbol_y).data
    u = np.clip(copula_df["u"].to_numpy(dtype=float), 1e-6, 1.0 - 1e-6)
    v = np.clip(copula_df["v"].to_numpy(dtype=float), 1e-6, 1.0 - 1e-6)
    weights = copula_df["weight"].to_numpy(dtype=float)
    zx = norm.ppf(u)
    zy = norm.ppf(v)
    series = pd.Series(
        {
            "gaussian_copula_rho": _weighted_corr_from_values(zx, zy, weights),
        },
        name=f"{str(symbol_x).upper()}__{str(symbol_y).upper()}",
    )
    return AnnotatedResult(series, _metadata(snapshot, "gaussian_copula_summary", "Gaussian copula fit"))


def joint_shape_diagnostics(snapshot: JointDistributionSnapshot, *, symbol_x: str, symbol_y: str) -> AnnotatedResult:
    snapshot.require_success()
    x_idx = snapshot.symbol_index(symbol_x)
    y_idx = snapshot.symbol_index(symbol_y)
    x = snapshot.contract_rate_matrix[:, x_idx]
    y = snapshot.contract_rate_matrix[:, y_idx]
    weights = snapshot.state_weights
    matrix = _joint_matrix_dataframe(snapshot, symbol_x=symbol_x, symbol_y=symbol_y).to_numpy(dtype=float)
    flat = matrix.ravel()
    positive = flat[flat > 0]
    effective_cells = float(1.0 / np.sum(positive**2)) if positive.size else 0.0
    top_cell_mass = float(np.max(flat)) if flat.size else 0.0
    top2_mass = float(np.sum(np.sort(flat)[-2:])) if flat.size >= 2 else top_cell_mass

    peak_count = 0
    for row_idx in range(matrix.shape[0]):
        for col_idx in range(matrix.shape[1]):
            val = matrix[row_idx, col_idx]
            if val <= 0:
                continue
            neighbors = matrix[max(0, row_idx - 1): row_idx + 2, max(0, col_idx - 1): col_idx + 2]
            if val >= np.max(neighbors):
                peak_count += 1

    q10_x, q90_x = np.quantile(x, [0.1, 0.9])
    q10_y, q90_y = np.quantile(y, [0.1, 0.9])
    q25_x, q75_x = np.quantile(x, [0.25, 0.75])
    q25_y, q75_y = np.quantile(y, [0.25, 0.75])
    tail_mask = (x <= q10_x) | (x >= q90_x) | (y <= q10_y) | (y >= q90_y)
    center_mask = (x >= q25_x) & (x <= q75_x) & (y >= q25_y) & (y <= q75_y)

    tail_mass = float(np.sum(weights[tail_mask]))
    center_mass = float(np.sum(weights[center_mask]))
    tail_corr = _weighted_corr_from_values(x[tail_mask], y[tail_mask], weights[tail_mask]) if tail_mask.any() else float("nan")
    center_corr = _weighted_corr_from_values(x[center_mask], y[center_mask], weights[center_mask]) if center_mask.any() else float("nan")

    series = pd.Series(
        {
            "effective_cell_count": effective_cells,
            "top_cell_mass": top_cell_mass,
            "top2_cell_mass": top2_mass,
            "peak_count": float(peak_count),
            "regime_like_flag": float(1.0 if peak_count >= 2 and top2_mass >= 0.35 else 0.0),
            "center_mass": center_mass,
            "tail_mass": tail_mass,
            "tail_corr": tail_corr,
            "center_corr": center_corr,
        },
        name=f"{str(symbol_x).upper()}__{str(symbol_y).upper()}",
    )
    return AnnotatedResult(series, _metadata(snapshot, "joint_shape_diagnostics", "shape diagnostics"))


def mean_vector_change(comparison: JointDistributionComparison) -> AnnotatedResult:
    before = mean_vector(comparison.snapshot_before).data
    after = mean_vector(comparison.snapshot_after).data
    delta = after - before
    delta.name = "delta_mean_rate"
    return AnnotatedResult(delta, _comparison_metadata("exact aggregation", "mean vector change"))


def covariance_change(comparison: JointDistributionComparison) -> AnnotatedResult:
    before = covariance_matrix(comparison.snapshot_before).data
    after = covariance_matrix(comparison.snapshot_after).data
    return AnnotatedResult(after - before, _comparison_metadata("exact aggregation", "covariance change"))


def correlation_change(comparison: JointDistributionComparison) -> AnnotatedResult:
    before = correlation_matrix(comparison.snapshot_before).data
    after = correlation_matrix(comparison.snapshot_after).data
    return AnnotatedResult(after - before, _comparison_metadata("exact aggregation", "correlation change"))


def pair_joint_delta_matrix(comparison: JointDistributionComparison, *, symbol_x: str, symbol_y: str) -> AnnotatedResult:
    before = pair_joint_matrix(comparison.snapshot_before, symbol_x=symbol_x, symbol_y=symbol_y).data
    after = pair_joint_matrix(comparison.snapshot_after, symbol_x=symbol_x, symbol_y=symbol_y).data
    aligned_before, aligned_after = before.align(after, join="outer", fill_value=0.0)
    delta = aligned_after - aligned_before
    return AnnotatedResult(delta, _comparison_metadata("exact aggregation", "pair joint matrix delta"))


def top_pair_cell_changes(
    comparison: JointDistributionComparison,
    *,
    symbol_x: str,
    symbol_y: str,
    n: int = 10,
) -> AnnotatedResult:
    before = pair_joint_matrix(comparison.snapshot_before, symbol_x=symbol_x, symbol_y=symbol_y).data
    after = pair_joint_matrix(comparison.snapshot_after, symbol_x=symbol_x, symbol_y=symbol_y).data
    aligned_before, aligned_after = before.align(after, join="outer", fill_value=0.0)
    rows = []
    for x_value in aligned_before.index:
        for y_value in aligned_before.columns:
            prob_before = float(aligned_before.loc[x_value, y_value])
            prob_after = float(aligned_after.loc[x_value, y_value])
            rows.append(
                {
                    str(symbol_x).upper(): float(x_value),
                    str(symbol_y).upper(): float(y_value),
                    "probability_before": prob_before,
                    "probability_after": prob_after,
                    "delta_probability": prob_after - prob_before,
                }
            )
    df = pd.DataFrame(rows).sort_values("delta_probability", key=lambda s: np.abs(s), ascending=False).head(int(n)).reset_index(drop=True)
    return AnnotatedResult(df, _comparison_metadata("exact aggregation", "largest pair cell probability changes"))


def conditional_distribution_change(
    comparison: JointDistributionComparison,
    *,
    target_symbol: str,
    given_symbol: str,
    given_values: Optional[Sequence[float]] = None,
    given_range: Optional[Tuple[float, float]] = None,
) -> AnnotatedResult:
    before_payload = conditional_distribution(
        comparison.snapshot_before,
        target_symbol=target_symbol,
        given_symbol=given_symbol,
        given_values=given_values,
        given_range=given_range,
    ).data
    after_payload = conditional_distribution(
        comparison.snapshot_after,
        target_symbol=target_symbol,
        given_symbol=given_symbol,
        given_values=given_values,
        given_range=given_range,
    ).data
    before_df = before_payload["distribution"].set_index(str(target_symbol).upper())["probability"]
    after_df = after_payload["distribution"].set_index(str(target_symbol).upper())["probability"]
    aligned = _align_series(before_df, after_df).reset_index()
    result = {
        "distribution_delta": aligned,
        "js_divergence": _js_divergence(aligned["before"].to_numpy(dtype=float), aligned["after"].to_numpy(dtype=float)),
        "conditioning_probability_before": float(before_payload["conditioning_probability"]),
        "conditioning_probability_after": float(after_payload["conditioning_probability"]),
    }
    return AnnotatedResult(result, _comparison_metadata("exact aggregation", "conditional distribution change"))


def linear_combination_distribution_change(
    comparison: JointDistributionComparison,
    *,
    weights: Dict[str, float],
) -> AnnotatedResult:
    before_df = linear_combination_distribution(comparison.snapshot_before, weights=weights).data.set_index("linear_combination")["probability"]
    after_df = linear_combination_distribution(comparison.snapshot_after, weights=weights).data.set_index("linear_combination")["probability"]
    aligned = _align_series(before_df, after_df).reset_index()
    result = {
        "distribution_delta": aligned,
        "js_divergence": _js_divergence(aligned["before"].to_numpy(dtype=float), aligned["after"].to_numpy(dtype=float)),
    }
    return AnnotatedResult(result, _comparison_metadata("exact aggregation", "linear-combination distribution change"))


def copula_change_summary(comparison: JointDistributionComparison, *, symbol_x: str, symbol_y: str) -> AnnotatedResult:
    before_rank = rank_dependence_summary(comparison.snapshot_before, symbol_x=symbol_x, symbol_y=symbol_y).data
    after_rank = rank_dependence_summary(comparison.snapshot_after, symbol_x=symbol_x, symbol_y=symbol_y).data
    before_gauss = gaussian_copula_summary(comparison.snapshot_before, symbol_x=symbol_x, symbol_y=symbol_y).data
    after_gauss = gaussian_copula_summary(comparison.snapshot_after, symbol_x=symbol_x, symbol_y=symbol_y).data
    series = pd.Series(
        {
            "spearman_before": float(before_rank["spearman"]),
            "spearman_after": float(after_rank["spearman"]),
            "spearman_delta": float(after_rank["spearman"] - before_rank["spearman"]),
            "kendall_before": float(before_rank["kendall_tau_b"]),
            "kendall_after": float(after_rank["kendall_tau_b"]),
            "kendall_delta": float(after_rank["kendall_tau_b"] - before_rank["kendall_tau_b"]),
            "gaussian_rho_before": float(before_gauss["gaussian_copula_rho"]),
            "gaussian_rho_after": float(after_gauss["gaussian_copula_rho"]),
            "gaussian_rho_delta": float(after_gauss["gaussian_copula_rho"] - before_gauss["gaussian_copula_rho"]),
        },
        name=f"{str(symbol_x).upper()}__{str(symbol_y).upper()}",
    )
    return AnnotatedResult(series, _comparison_metadata("smoothed or fitted approximation", "copula change summary"))
