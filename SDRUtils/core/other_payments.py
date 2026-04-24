"""Other-payment field decomposition.

[#57]-[#62] Other payment amount / type / currency. Tech Spec recognises
three mutually-distinct payment categories that must NOT be aggregated:

- UFRO: Upfront Fee / Roll-Over (premium-like)
- UWIN: Upfront Windup / Settlement (termination settlement)
- PEXH: Payment on Early Exercise / Hedge (exercise settlement)

The existing pipeline sums `Other payment amount` across any row carrying
`Other payment type` — which adds premiums to settlements when a single
swap has multiple payment rows. This module surfaces each category into
its own column so aggregators can pick the correct one.
"""
from __future__ import annotations

from typing import Dict

import pandas as pd


_PAYMENT_TYPES = ("UFRO", "UWIN", "PEXH")


def categorize_other_payment(
    amount: object,
    payment_type: object,
) -> Dict[str, float]:
    """Return ``{UFRO: x, UWIN: 0, PEXH: 0}`` based on [#57] payment type.

    Unknown payment types produce an empty dict so downstream aggregators
    can choose to log-and-skip.
    """
    if amount is None or (isinstance(amount, float) and pd.isna(amount)):
        return {k: 0.0 for k in _PAYMENT_TYPES}
    try:
        val = float(str(amount).replace(",", ""))
    except (TypeError, ValueError):
        return {k: 0.0 for k in _PAYMENT_TYPES}

    key = str(payment_type).strip().upper() if payment_type is not None else ""
    out = {k: 0.0 for k in _PAYMENT_TYPES}
    if key in out:
        out[key] = val
    return out


def enrich_other_payments_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Materialize ``other_payment_ufro``, ``_uwin``, ``_pexh`` columns.

    Reads ``Other payment amount`` and ``Other payment type`` if present;
    falls back to the snake_case equivalents.
    """
    amount_col = (
        "Other payment amount"
        if "Other payment amount" in df.columns
        else "other_payment_amount"
        if "other_payment_amount" in df.columns
        else None
    )
    type_col = (
        "Other payment type"
        if "Other payment type" in df.columns
        else "other_payment_type"
        if "other_payment_type" in df.columns
        else None
    )
    if amount_col is None or type_col is None:
        for k in _PAYMENT_TYPES:
            df[f"other_payment_{k.lower()}"] = 0.0
        return df

    records = []
    for i in range(len(df)):
        records.append(
            categorize_other_payment(df[amount_col].iat[i], df[type_col].iat[i])
        )
    for k in _PAYMENT_TYPES:
        df[f"other_payment_{k.lower()}"] = [r[k] for r in records]
    return df
