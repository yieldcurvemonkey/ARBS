from __future__ import annotations

from typing import Sequence

import pandas as pd

SOFR_UNDERLIER_NAMES = [
    "USD-SOFR-COMPOUND",
    "USD-SOFR-OIS Compound",
]

SOFR_UNDERLIER_NAMES_MISC = [
    "USD-SOFR CME Term",
    "USD-SOFR",
    "USD-SOFR ICE Swap Rate",
    "USD-SOFR Average 30D ",
]

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
    underlier_names = list(SOFR_UNDERLIER_NAMES)
    if include_misc:
        underlier_names.extend(SOFR_UNDERLIER_NAMES_MISC)
    df = df.copy()
    mask = df["UPI Underlier Name"].isin(underlier_names) & df["UPI FISN"].isin(SOFR_FISN_VALUES) & df["Action type"].isin(list(action_types))
    return df[mask]


def is_sofr_swap(row: pd.Series) -> bool:
    underlier = row.get("UPI Underlier Name", "")
    fisn = row.get("UPI FISN", "")
    return underlier in SOFR_UNDERLIER_NAMES and fisn in SOFR_FISN_VALUES


def sofr_swap_trades(df: pd.DataFrame, *, include_misc: bool = True) -> pd.DataFrame:
    underlier_names = list(SOFR_UNDERLIER_NAMES)
    if include_misc:
        underlier_names.extend(SOFR_UNDERLIER_NAMES_MISC)
    df = df.copy()
    mask = df["UPI Underlier Name"].isin(underlier_names) & df["UPI FISN"].isin(SOFR_FISN_VALUES)
    return df[mask]


def sofr_swaption_trades(
    df: pd.DataFrame,
    *,
    action_types: Sequence[str] = ("NEWT",),
) -> pd.DataFrame:
    df = df.copy()
    fisn_mask = (
        df["UPI FISN"].str.contains("Call", case=False, na=False)
        | df["UPI FISN"].str.contains("Put", case=False, na=False)
        | df["UPI FISN"].str.contains("O P", case=False, na=False)
    )
    underlier_mask = df["UPI Underlier Name"].isin(SOFR_UNDERLIER_NAMES + SOFR_UNDERLIER_NAMES_MISC)
    action_mask = df["Action type"].isin(list(action_types))
    return df[fisn_mask & underlier_mask & action_mask]


def sofr_cap_floor_trades(
    df: pd.DataFrame,
    *,
    action_types: Sequence[str] = ("NEWT",),
) -> pd.DataFrame:
    df = df.copy()
    fisn_mask = df["UPI FISN"].str.contains("CAP", case=False, na=False) | df["UPI FISN"].str.contains("FLOOR", case=False, na=False)
    underlier_mask = df["UPI Underlier Name"].isin(SOFR_UNDERLIER_NAMES + SOFR_UNDERLIER_NAMES_MISC)
    action_mask = df["Action type"].isin(list(action_types))
    return df[fisn_mask & underlier_mask & action_mask]
