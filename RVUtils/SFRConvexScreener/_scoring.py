"""Cross-sectional z-score normalization, composite score, liquidity filters."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def zscore(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    sd = s.std(ddof=0)
    if not np.isfinite(sd) or sd <= 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / sd


def composite_score_series(
    df: pd.DataFrame,
    *,
    weights: Sequence[float],
    columns: Sequence[str],
) -> pd.Series:
    if len(weights) != len(columns):
        raise ValueError("weights and columns must have same length")
    z_df = pd.concat([zscore(df[c]) for c in columns], axis=1)
    z_df.columns = list(columns)
    return z_df.mul(list(weights), axis=1).sum(axis=1)


def apply_liquidity_filters(
    df: pd.DataFrame,
    *,
    min_open_interest_per_leg: int,
    min_avg_daily_volume_per_leg: int,
    max_bid_ask_bp: float,
    min_carry_adjusted_ev_bp: float,
) -> pd.DataFrame:
    """Drop rows that fail any of the configured liquidity / EV filters.

    Expects optional columns: ``min_leg_oi``, ``min_leg_volume``,
    ``max_leg_bid_ask_bp``, ``carry_adjusted_ev_bp``. Missing columns are
    treated as pass-through (do not exclude on missing data).
    """
    mask = pd.Series(True, index=df.index)
    if "min_leg_oi" in df.columns:
        mask &= df["min_leg_oi"].fillna(np.inf) >= min_open_interest_per_leg
    if "min_leg_volume" in df.columns:
        mask &= df["min_leg_volume"].fillna(np.inf) >= min_avg_daily_volume_per_leg
    if "max_leg_bid_ask_bp" in df.columns:
        mask &= df["max_leg_bid_ask_bp"].fillna(-np.inf) <= max_bid_ask_bp
    if "carry_adjusted_ev_bp" in df.columns:
        mask &= df["carry_adjusted_ev_bp"].fillna(-np.inf) >= min_carry_adjusted_ev_bp
    return df.loc[mask].copy()
