"""Pandas export helpers for shared-state joint distribution results."""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

import pandas as pd

from RVUtils.ImpliedDistribution._types import JointDistributionComparison, JointDistributionSnapshot


def joint_state_probabilities_to_dataframe(snapshot: JointDistributionSnapshot) -> pd.DataFrame:
    return snapshot.state_probability_table().data.copy()


def joint_pair_matrix_to_dataframe(snapshot: JointDistributionSnapshot, *, symbol_x: str, symbol_y: str) -> pd.DataFrame:
    return snapshot.pair_joint_matrix(symbol_x, symbol_y).data.copy()


def joint_marginal_to_dataframe(snapshot: JointDistributionSnapshot, *, symbol: str) -> pd.DataFrame:
    return snapshot.marginal_distribution(symbol).data.copy()


def conditional_distribution_to_dataframe(
    snapshot: JointDistributionSnapshot,
    *,
    target_symbol: str,
    given_symbol: str,
    given_values: Optional[Sequence[float]] = None,
    given_range: Optional[Tuple[float, float]] = None,
) -> pd.DataFrame:
    payload = snapshot.conditional_distribution(
        target_symbol=target_symbol,
        given_symbol=given_symbol,
        given_values=given_values,
        given_range=given_range,
    ).data
    df = payload["distribution"].copy()
    df.attrs["conditioning_probability"] = float(payload["conditioning_probability"])
    df.attrs["selector"] = payload["selector"]
    return df


def linear_combination_to_dataframe(snapshot: JointDistributionSnapshot, *, weights: Dict[str, float]) -> pd.DataFrame:
    return snapshot.linear_combination_distribution(weights).data.copy()


def joint_delta_to_dataframe(comparison: JointDistributionComparison, *, symbol_x: str, symbol_y: str) -> pd.DataFrame:
    return comparison.pair_joint_delta(symbol_x, symbol_y).data.copy()


def top_pair_cell_changes_to_dataframe(
    comparison: JointDistributionComparison,
    *,
    symbol_x: str,
    symbol_y: str,
    n: int = 10,
) -> pd.DataFrame:
    return comparison.top_pair_cell_changes(symbol_x, symbol_y, n=n).data.copy()
