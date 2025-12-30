"""
USD Trade Filters.

Provides filtering utilities for USD swap trades.
"""

from typing import Optional

import pandas as pd
import numpy as np


def new_sofr_swap_trades(
    df: pd.DataFrame,
    *,
    action_col: str = "Action type",
    event_col: str = "Event type",
    product_col: str = "product_type",
    product_values: Optional[list] = None,
    currency_col: str = "notional_currency",
    currency_value: str = "USD",
    underlier_col: str = "UPI Underlier Name",
) -> pd.DataFrame:
    """
    Filter DataFrame to only new SOFR swap trades.

    Filters for:
    - Action type: NEWT (new trade)
    - Event type: TRAD (trade)
    - Product type: OIS_SWAP (or specified products)
    - Currency: USD
    - Underlier: Contains "SOFR"

    Args:
        df: Input DataFrame with SDR trades
        action_col: Column containing action type
        event_col: Column containing event type
        product_col: Column containing product type (if classified)
        product_values: List of product types to include (default: ["OIS_SWAP"])
        currency_col: Column containing currency
        currency_value: Currency to filter for
        underlier_col: Column containing underlier name

    Returns:
        Filtered DataFrame
    """
    if df.empty:
        return df

    if product_values is None:
        product_values = ["OIS_SWAP"]

    out = df.copy()
    mask = np.ones(len(out), dtype=bool)

    # Action type filter
    if action_col in out.columns:
        mask &= out[action_col].astype("string").str.upper().values == "NEWT"

    # Event type filter
    if event_col in out.columns:
        mask &= out[event_col].astype("string").str.upper().values == "TRAD"

    # Currency filter
    if currency_col in out.columns:
        mask &= out[currency_col].astype("string").str.upper().values == currency_value

    # Product type filter (if column exists and is classified)
    if product_col in out.columns:
        mask &= out[product_col].isin(product_values).values

    # Underlier filter
    if underlier_col in out.columns:
        mask &= out[underlier_col].astype("string").str.upper().str.contains("SOFR", na=False).values

    return out.loc[mask].reset_index(drop=True)


def cleared_trades_only(
    df: pd.DataFrame,
    *,
    cleared_col: str = "Cleared",
    cleared_value: str = "Y",
) -> pd.DataFrame:
    """
    Filter DataFrame to only cleared trades.

    Args:
        df: Input DataFrame
        cleared_col: Column containing cleared flag
        cleared_value: Value indicating cleared

    Returns:
        Filtered DataFrame
    """
    if df.empty or cleared_col not in df.columns:
        return df

    mask = df[cleared_col].astype("string").str.upper().values == cleared_value
    return df.loc[mask].reset_index(drop=True)


def uncleared_trades_only(
    df: pd.DataFrame,
    *,
    cleared_col: str = "Cleared",
    cleared_value: str = "Y",
) -> pd.DataFrame:
    """
    Filter DataFrame to only uncleared trades.

    Args:
        df: Input DataFrame
        cleared_col: Column containing cleared flag
        cleared_value: Value indicating cleared

    Returns:
        Filtered DataFrame
    """
    if df.empty or cleared_col not in df.columns:
        return df

    mask = df[cleared_col].astype("string").str.upper().values != cleared_value
    return df.loc[mask].reset_index(drop=True)


def spot_trades_only(
    df: pd.DataFrame,
    *,
    forward_label_col: str = "forward_label",
    spot_value: str = "spot",
) -> pd.DataFrame:
    """
    Filter DataFrame to only spot-starting trades.

    Args:
        df: Input DataFrame
        forward_label_col: Column containing forward label
        spot_value: Value indicating spot

    Returns:
        Filtered DataFrame
    """
    if df.empty or forward_label_col not in df.columns:
        return df

    mask = df[forward_label_col].astype("string").str.lower().values == spot_value
    return df.loc[mask].reset_index(drop=True)


def forward_trades_only(
    df: pd.DataFrame,
    *,
    forward_label_col: str = "forward_label",
    spot_value: str = "spot",
) -> pd.DataFrame:
    """
    Filter DataFrame to only forward-starting trades.

    Args:
        df: Input DataFrame
        forward_label_col: Column containing forward label
        spot_value: Value indicating spot

    Returns:
        Filtered DataFrame
    """
    if df.empty or forward_label_col not in df.columns:
        return df

    mask = df[forward_label_col].astype("string").str.lower().values != spot_value
    return df.loc[mask].reset_index(drop=True)
