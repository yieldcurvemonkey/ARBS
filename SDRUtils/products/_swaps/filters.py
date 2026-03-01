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

USD_SWAP_FISN_VALUES = list(SOFR_FISN_VALUES)


def _series(df: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series(default, index=df.index)


def _usd_underlier_or_ccy_mask(df: pd.DataFrame) -> pd.Series:
    underlier = _series(df, "UPI Underlier Name").astype("string").str.strip().str.upper()
    ccy_1 = _series(df, "Notional currency-Leg 1").astype("string").str.strip().str.upper()
    ccy_2 = _series(df, "Notional currency-Leg 2").astype("string").str.strip().str.upper()
    underlier_mask = underlier.str.startswith("USD-", na=False)
    return underlier_mask | ccy_1.eq("USD") | ccy_2.eq("USD")


def _usd_swap_mask(df: pd.DataFrame) -> pd.Series:
    fisn = _series(df, "UPI FISN").astype("string").str.strip()
    return fisn.isin(USD_SWAP_FISN_VALUES) & _usd_underlier_or_ccy_mask(df)


def _legacy_sofr_underlier_mask(df: pd.DataFrame, *, include_misc: bool) -> pd.Series:
    underlier_names = list(SOFR_UNDERLIER_NAMES)
    if include_misc:
        underlier_names.extend(SOFR_UNDERLIER_NAMES_MISC)
    underlier = _series(df, "UPI Underlier Name")
    return underlier.isin(underlier_names)


def new_usd_swap_trades(
    df: pd.DataFrame,
    *,
    action_types: Sequence[str] = ("NEWT",),
) -> pd.DataFrame:
    return usd_swap_trades(df, action_types=action_types)


def usd_swap_trades(
    df: pd.DataFrame,
    *,
    action_types: Sequence[str] | None = None,
) -> pd.DataFrame:
    df = df.copy()
    mask = _usd_swap_mask(df)
    if action_types is not None:
        action = _series(df, "Action type")
        mask &= action.isin(list(action_types))
    return df[mask]


def is_usd_swap(row: pd.Series) -> bool:
    underlier = str(row.get("UPI Underlier Name", "")).strip().upper()
    fisn = str(row.get("UPI FISN", "")).strip()
    ccy_1 = str(row.get("Notional currency-Leg 1", "")).strip().upper()
    ccy_2 = str(row.get("Notional currency-Leg 2", "")).strip().upper()
    return fisn in USD_SWAP_FISN_VALUES and (underlier.startswith("USD-") or ccy_1 == "USD" or ccy_2 == "USD")


def new_sofr_swap_trades(
    df: pd.DataFrame,
    *,
    include_misc: bool = False,
    action_types: Sequence[str] = ("NEWT",),
    legacy_underlier_only: bool = True,
) -> pd.DataFrame:
    out = new_usd_swap_trades(df, action_types=action_types)
    if legacy_underlier_only:
        out = out[_legacy_sofr_underlier_mask(out, include_misc=include_misc)]
    return out


def is_sofr_swap(
    row: pd.Series,
    *,
    include_misc: bool = False,
    legacy_underlier_only: bool = True,
) -> bool:
    if not is_usd_swap(row):
        return False
    if not legacy_underlier_only:
        return True
    names = list(SOFR_UNDERLIER_NAMES)
    if include_misc:
        names.extend(SOFR_UNDERLIER_NAMES_MISC)
    underlier = row.get("UPI Underlier Name", "")
    return underlier in names


def sofr_swap_trades(
    df: pd.DataFrame,
    *,
    include_misc: bool = True,
    legacy_underlier_only: bool = True,
) -> pd.DataFrame:
    out = usd_swap_trades(df)
    if legacy_underlier_only:
        out = out[_legacy_sofr_underlier_mask(out, include_misc=include_misc)]
    return out


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


__all__ = [
    "USD_SWAP_FISN_VALUES",
    "SOFR_UNDERLIER_NAMES",
    "SOFR_UNDERLIER_NAMES_MISC",
    "SOFR_FISN_VALUES",
    "usd_swap_trades",
    "new_usd_swap_trades",
    "is_usd_swap",
    "sofr_swap_trades",
    "new_sofr_swap_trades",
    "is_sofr_swap",
    "sofr_swaption_trades",
    "sofr_cap_floor_trades",
]
