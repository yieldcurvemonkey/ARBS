"""
USD product filters for SDR data.

Provides filter functions for identifying USD derivatives in SDR data.
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd


# Standard SOFR OIS underlier names
SOFR_UNDERLIER_NAMES = [
    "USD-SOFR-COMPOUND",
    "USD-SOFR-OIS Compound",
]

# Additional SOFR-related underlier names (less common)
SOFR_UNDERLIER_NAMES_MISC = [
    "USD-SOFR CME Term",
    "USD-SOFR",
    "USD-SOFR ICE Swap Rate",
    "USD-SOFR Average 30D ",
]

# Standard SOFR FISN values
SOFR_FISN_VALUES = [
    "NA/Swap OIS USD",
    "NA/Swap Fxd Flt USD",
]


def new_sofr_swap_trades(
    df: pd.DataFrame,
    *,
    include_misc: bool = False,
    action_types: Sequence[str] = ("NEWT",),
) -> pd.DataFrame:
    """
    Filter SDR DataFrame to new SOFR OIS swap trades.

    Args:
        df: Raw SDR DataFrame
        include_misc: Include less common SOFR underlier names
        action_types: Action types to include (default: new trades only)

    Returns:
        Filtered DataFrame with only SOFR swap trades
    """
    underlier_names = list(SOFR_UNDERLIER_NAMES)
    if include_misc:
        underlier_names.extend(SOFR_UNDERLIER_NAMES_MISC)

    df = df.copy()
    mask = (
        df["UPI Underlier Name"].isin(underlier_names)
        & df["UPI FISN"].isin(SOFR_FISN_VALUES)
        & df["Action type"].isin(list(action_types))
    )
    return df[mask]


def is_sofr_swap(row: pd.Series) -> bool:
    """
    Check if a single SDR row is a SOFR OIS swap.

    Args:
        row: SDR data row

    Returns:
        True if the row is a SOFR swap
    """
    underlier = row.get("UPI Underlier Name", "")
    fisn = row.get("UPI FISN", "")

    return (
        underlier in SOFR_UNDERLIER_NAMES
        and fisn in SOFR_FISN_VALUES
    )


def sofr_swaption_trades(
    df: pd.DataFrame,
    *,
    action_types: Sequence[str] = ("NEWT",),
) -> pd.DataFrame:
    """
    Filter SDR DataFrame to SOFR swaption trades.

    Args:
        df: Raw SDR DataFrame
        action_types: Action types to include

    Returns:
        Filtered DataFrame with only SOFR swaption trades
    """
    df = df.copy()

    # Look for swaption indicators in FISN
    fisn_mask = (
        df["UPI FISN"].str.contains("Call", case=False, na=False)
        | df["UPI FISN"].str.contains("Put", case=False, na=False)
        | df["UPI FISN"].str.contains("O P", case=False, na=False)
    )

    underlier_mask = df["UPI Underlier Name"].isin(
        SOFR_UNDERLIER_NAMES + SOFR_UNDERLIER_NAMES_MISC
    )

    action_mask = df["Action type"].isin(list(action_types))

    return df[fisn_mask & underlier_mask & action_mask]


def sofr_cap_floor_trades(
    df: pd.DataFrame,
    *,
    action_types: Sequence[str] = ("NEWT",),
) -> pd.DataFrame:
    """
    Filter SDR DataFrame to SOFR cap/floor trades.

    Args:
        df: Raw SDR DataFrame
        action_types: Action types to include

    Returns:
        Filtered DataFrame with only SOFR cap/floor trades
    """
    df = df.copy()

    fisn_mask = (
        df["UPI FISN"].str.contains("CAP", case=False, na=False)
        | df["UPI FISN"].str.contains("FLOOR", case=False, na=False)
    )

    underlier_mask = df["UPI Underlier Name"].isin(
        SOFR_UNDERLIER_NAMES + SOFR_UNDERLIER_NAMES_MISC
    )

    action_mask = df["Action type"].isin(list(action_types))

    return df[fisn_mask & underlier_mask & action_mask]
