"""
Trade quality flagging: identify off-market trades, upfront payments, and outliers.

UFRO (upfront other) payments indicate trades at off-market rates where
the NPV difference is settled via cash. These should be excluded from
VWAP calculations and flagged in analytics.
"""
from __future__ import annotations

from enum import Enum
from typing import List

import numpy as np
import pandas as pd


class TradeQualityFlag(str, Enum):
    """Flags indicating potential quality issues with a trade."""

    UFRO = "UFRO"
    OFF_MARKET = "OFF_MARKET"
    CAPPED_NOTIONAL = "CAPPED_NOTIONAL"
    STALE_RATE = "STALE_RATE"
    COMPRESSION = "COMPRESSION"


def _is_true_flag(value) -> bool:
    """Return True only for explicit true-like scalar flag values."""
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return bool(value)


def flag_upfront_payments(
    df: pd.DataFrame,
    payment_type_col: str = "other_payment_type",
    payment_amount_col: str = "other_payment_amount",
) -> pd.DataFrame:
    """Flag trades with upfront (UFRO) payments.

    UFRO payments indicate the trade was executed at an off-market rate
    and the NPV difference was settled via a cash payment.

    Args:
        df: DataFrame with payment columns.
        payment_type_col: Column containing payment type strings.
        payment_amount_col: Column containing payment amounts.

    Returns:
        Copy of *df* with added columns ``is_ufro`` (bool) and
        ``ufro_amount`` (float).
    """
    df = df.copy()

    pmt_type = df.get(payment_type_col)
    if pmt_type is None:
        pmt_type = pd.Series("", index=df.index)
    type_match = pmt_type.astype(str).str.contains("UFRO", na=False)

    pmt_amt_raw = df.get(payment_amount_col)
    if pmt_amt_raw is None:
        pmt_amt_raw = pd.Series(0, index=df.index)
    pmt_amt = pd.to_numeric(pmt_amt_raw, errors="coerce").fillna(0)

    df["is_ufro"] = type_match & (pmt_amt > 0)
    df["ufro_amount"] = np.where(df["is_ufro"], pmt_amt, 0.0)

    return df


def flag_off_market_trades(
    df: pd.DataFrame,
    rate_col: str = "fixed_rate",
    group_col: str = "tenor_label",
    date_col: str = "execution_date",
    threshold_bp: float = 10.0,
) -> pd.DataFrame:
    """Flag trades whose rate deviates from the group+date median OR
    that are seasoned off-market swaps (past effective date + UFRO).

    Rate-outlier detection: for each combination of *group_col* and
    *date_col*, computes the median rate.  Trades where
    ``|rate - median| > threshold_bp / 10_000`` are flagged.

    Seasoned detection: trades where ``effective_date < execution_date``
    AND ``is_ufro == True`` are flagged as off-market seasoned swaps
    (novated/traded at a non-par price with an upfront payment).

    Args:
        df: DataFrame with rate, grouping, and date columns.
            Expects ``is_ufro`` to be set by a prior call to
            :func:`flag_upfront_payments`.
        rate_col: Column containing the fixed rate.
        group_col: Column to group by (e.g. ``tenor_label``).
        date_col: Column containing execution dates.
        threshold_bp: Deviation threshold in basis points.

    Returns:
        Copy of *df* with added columns ``is_off_market`` (bool),
        ``rate_deviation_bp`` (float, signed), and
        ``off_market_reason`` (string or NA).
    """
    df = df.copy()
    rate = pd.to_numeric(df.get(rate_col), errors="coerce")

    # --- Rate deviation check ---
    group_keys = [date_col, group_col]
    for col in group_keys:
        if col not in df.columns:
            df["is_off_market"] = False
            df["rate_deviation_bp"] = 0.0
            df["off_market_reason"] = pd.NA
            return df

    medians = (
        df.assign(_rate=rate)
        .groupby(group_keys)["_rate"]
        .transform("median")
    )

    deviation = rate - medians
    deviation_bp = deviation * 10_000
    df["rate_deviation_bp"] = deviation_bp
    rate_outlier = deviation_bp.abs() > threshold_bp

    # --- Seasoned off-market: past effective date + UFRO ---
    exec_date = pd.to_datetime(df.get(date_col), errors="coerce").dt.normalize()
    eff_date = pd.to_datetime(df.get("effective_date"), errors="coerce").dt.normalize()
    is_ufro = df.get("is_ufro", pd.Series(False, index=df.index)).fillna(False).astype(bool)
    past_effective = exec_date.notna() & eff_date.notna() & (eff_date < exec_date)
    is_seasoned = past_effective & is_ufro

    df["is_off_market"] = rate_outlier | is_seasoned

    reason = pd.Series(pd.NA, index=df.index, dtype="string")
    reason.loc[rate_outlier & ~is_seasoned] = "rate_outlier"
    reason.loc[is_seasoned & ~rate_outlier] = "past_effective_with_ufro"
    reason.loc[rate_outlier & is_seasoned] = "past_effective_with_ufro,rate_outlier"
    df["off_market_reason"] = reason

    return df


def flag_capped_notional(
    df: pd.DataFrame,
    cap_col: str = "is_notional_capped",
) -> pd.DataFrame:
    """Flag trades with capped notional amounts.

    If the *cap_col* column exists the flag mirrors it; otherwise all
    trades are marked ``False``.

    Args:
        df: DataFrame with optional notional-cap indicator.
        cap_col: Column name for the capped-notional indicator.

    Returns:
        Copy of *df* with added column ``is_capped`` (bool).
    """
    df = df.copy()

    if cap_col in df.columns:
        df["is_capped"] = df[cap_col].map(_is_true_flag).astype(bool)
    else:
        df["is_capped"] = False

    return df


def flag_outliers(
    df: pd.DataFrame,
    threshold_bp: float = 10.0,
) -> pd.DataFrame:
    """Composite quality check -- runs all flag functions.

    Applies :func:`flag_upfront_payments`, :func:`flag_off_market_trades`,
    and :func:`flag_capped_notional`, then collects per-trade quality flags
    into a single ``quality_flags`` list column.

    Args:
        df: DataFrame with the columns expected by each sub-function.
        threshold_bp: Deviation threshold passed to
            :func:`flag_off_market_trades`.

    Returns:
        Copy of *df* with all flag columns plus a ``quality_flags``
        column containing a list of :class:`TradeQualityFlag` string
        values for each trade.
    """
    df = flag_upfront_payments(df)
    df = flag_off_market_trades(df, threshold_bp=threshold_bp)
    df = flag_capped_notional(df)

    def _collect_flags(row) -> List[str]:
        flags: List[str] = []
        if _is_true_flag(row.get("is_ufro", False)):
            flags.append(TradeQualityFlag.UFRO.value)
        if _is_true_flag(row.get("is_off_market", False)):
            flags.append(TradeQualityFlag.OFF_MARKET.value)
        if _is_true_flag(row.get("is_capped", False)):
            flags.append(TradeQualityFlag.CAPPED_NOTIONAL.value)
        return flags

    df["quality_flags"] = df.apply(_collect_flags, axis=1)

    return df
