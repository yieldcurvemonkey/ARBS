from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd


def _contains_any(series: pd.Series, needles: Iterable[str]) -> pd.Series:
    values = series.astype(str).str.upper()
    mask = pd.Series(False, index=series.index)
    for needle in needles:
        mask |= values.str.contains(needle.upper(), na=False)
    return mask


def new_sofr_swap_trades(
    df: pd.DataFrame,
    *,
    underlier_col: str = "UPI Underlier Name",
    fisn_col: str = "UPI FISN",
    action_col: Optional[str] = None,
    action_values: Iterable[str] = ("NEW",),
) -> pd.DataFrame:
    """Filter dataframe to new USD SOFR OIS swap trades when columns are available."""
    if df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    if underlier_col in df.columns:
        mask &= _contains_any(df[underlier_col], ["SOFR"])

    if fisn_col in df.columns:
        mask &= _contains_any(df[fisn_col], ["OIS", "SWAP"])

    if action_col and action_col in df.columns:
        mask &= _contains_any(df[action_col], action_values)

    return df.loc[mask]
