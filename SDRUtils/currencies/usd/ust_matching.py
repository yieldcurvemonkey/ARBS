"""
USD UST Maturity Matching.

Provides utilities for matching swap maturities to UST reference data.
"""

from typing import Optional, Sequence

import pandas as pd


def match_swaps_to_ust(
    df: pd.DataFrame,
    *,
    swap_maturity_col: str = "expiration_date",
    product_col: str = "product_type",
    product_values: Sequence[str] = ("OIS_SWAP",),
    currency_col: str = "notional_currency",
    require_usd: bool = True,
    usd_value: str = "USD",
    ust_ref_source: str = "fiscaldata",
    ust_force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Add UST reference fields to swaps whose maturity date matches a UST maturity.

    This is a matched maturity join - it does NOT attempt "nearest on-the-run" mapping.

    Output columns (if matched):
    - ust_cusip, ust_oi, ust_security_type, ust_issue_date, ust_coupon, ...
    - matched_ust_maturity (bool)

    Args:
        df: DataFrame with swap trades
        swap_maturity_col: Column containing swap maturity dates
        product_col: Column containing product types
        product_values: Product types to consider
        currency_col: Column containing currency codes
        require_usd: Only match USD swaps
        usd_value: Value representing USD in currency column
        ust_ref_source: Source for UST reference data
        ust_force_refresh: Force refresh of UST reference cache

    Returns:
        DataFrame with UST matching columns added
    """
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

    if df.empty:
        return df

    out = df.copy()

    # Candidate swaps
    m = out[product_col].isin(list(product_values)).values
    if require_usd and currency_col in out.columns:
        m &= out[currency_col].astype("string").values == usd_value

    if not m.any():
        out["matched_ust_maturity"] = False
        return out

    # Load UST reference data
    ref = update_reference_data(source=ust_ref_source, force_refresh=ust_force_refresh).copy()

    if "maturity_date" in ref.columns:
        ref["maturity_date"] = pd.to_datetime(ref["maturity_date"], errors="coerce").dt.date
    if "issue_date" in ref.columns:
        ref["issue_date"] = pd.to_datetime(ref["issue_date"], errors="coerce").dt.date

    # Build maturity map
    maturity_map = _build_maturity_to_ust_map(ref)

    def _to_date_series(x: pd.Series) -> pd.Series:
        return pd.to_datetime(x, errors="coerce", utc=True).dt.date

    # Normalize swap maturity date
    swap_mat = _to_date_series(out.loc[m, swap_maturity_col])
    tmp = out.loc[m, ["trade_id"]].copy() if "trade_id" in out.columns else out.loc[m, []].copy()
    tmp["_swap_maturity_date"] = swap_mat.values

    # Merge
    tmp = tmp.merge(
        maturity_map,
        left_on="_swap_maturity_date",
        right_on="maturity_date",
        how="left",
    )

    # Write back
    out["matched_ust_maturity"] = False
    matched = tmp["ust_cusip"].notna().values

    idx = out.index[m]
    out.loc[idx, "matched_ust_maturity"] = matched

    for c in [c for c in tmp.columns if c.startswith("ust_")]:
        out.loc[idx, c] = tmp[c].values

    out.loc[idx, "swap_maturity_date"] = tmp["_swap_maturity_date"].values

    return out


def _build_maturity_to_ust_map(
    ust_ref: pd.DataFrame,
    prefer_oi: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """
    Build 1 row per maturity_date, choosing best CUSIP.

    Prefers latest issue_date (reopenings share maturity).
    """
    ref = ust_ref.copy()

    if prefer_oi is not None and "oi" in ref.columns:
        ref = ref[ref["oi"].isin(list(prefer_oi))].copy()

    if "maturity_date" not in ref.columns or "cusip" not in ref.columns:
        raise KeyError("UST reference data must include columns: 'maturity_date', 'cusip'")

    ref = ref.dropna(subset=["maturity_date", "cusip"]).copy()

    # Sort so "best" is last
    sort_cols = []
    asc = []
    if "issue_date" in ref.columns:
        sort_cols.append("issue_date")
        asc.append(True)
    sort_cols.append("cusip")
    asc.append(True)

    ref = ref.sort_values(sort_cols, ascending=asc, kind="mergesort")

    keep_cols = [
        c
        for c in [
            "maturity_date",
            "cusip",
            "oi",
            "security_type",
            "security_term",
            "issue_date",
            "original_security_term",
            "interest_rate",
        ]
        if c in ref.columns
    ]

    best = ref[keep_cols].drop_duplicates(subset=["maturity_date"], keep="last").copy()
    best = best.rename(
        columns={
            "cusip": "ust_cusip",
            "oi": "ust_oi",
            "security_type": "ust_security_type",
            "security_term": "ust_security_term",
            "issue_date": "ust_issue_date",
            "original_security_term": "ust_original_security_term",
            "interest_rate": "ust_coupon",
        }
    )
    return best
