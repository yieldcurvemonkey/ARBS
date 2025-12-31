from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd

import re
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay


from SDRUtils.config import PACKAGE_TYPES
from SDRUtils.packages.base import PackageDetector


def _load_ust_reference_data(
    *,
    source: str = "fiscaldata",
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Load UST reference data from the specified source.

    Args:
        source: Data source (currently supports "fiscaldata")
        force_refresh: Force refresh from source

    Returns:
        DataFrame with UST reference data
    """
    from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

    ref = update_reference_data(source=source, force_refresh=force_refresh).copy()

    # Normalize key date fields
    if "maturity_date" in ref.columns:
        ref["maturity_date"] = pd.to_datetime(ref["maturity_date"], errors="coerce").dt.date
    if "issue_date" in ref.columns:
        ref["issue_date"] = pd.to_datetime(ref["issue_date"], errors="coerce").dt.date

    return ref


def _build_maturity_to_ust_map(
    ust_ref: pd.DataFrame,
    *,
    prefer_oi: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """
    Build a mapping from maturity date to UST reference data.

    Returns 1 row per maturity_date, choosing the "best" CUSIP:
    - Prefers latest issue_date (reopenings share maturity)
    - Deterministic tie-breaks by CUSIP

    Args:
        ust_ref: UST reference data
        prefer_oi: Optional list of original issue types to prefer

    Returns:
        DataFrame mapping maturity dates to UST info
    """
    ref = ust_ref.copy()

    if prefer_oi is not None and "oi" in ref.columns:
        ref = ref[ref["oi"].isin(list(prefer_oi))].copy()

    if "maturity_date" not in ref.columns or "cusip" not in ref.columns:
        raise KeyError("UST reference data must include columns: 'maturity_date', 'cusip'")

    ref = ref.dropna(subset=["maturity_date", "cusip"]).copy()

    # Sort so "best" is last, then drop_duplicates(keep="last")
    sort_cols = []
    asc = []
    if "issue_date" in ref.columns:
        sort_cols.append("issue_date")
        asc.append(True)  # older -> newer
    # Deterministic tie-breakers
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


def _to_date_series(x: pd.Series) -> pd.Series:
    """Convert a series to date objects."""
    return pd.to_datetime(x, errors="coerce", utc=True).dt.date


def detect_mms_trades_df(
    df: pd.DataFrame,
    *,
    # Swap columns
    product_col: str = "product_type",
    product_values: Sequence[str] = ("OIS_SWAP",),
    package_col: str = "package_type",
    trade_id_col: str = "trade_id",
    swap_maturity_col: str = "expiration_date",
    currency_col: str = "notional_currency",
    require_usd: bool = True,
    usd_value: str = "USD",
    # UST reference
    ust_ref_source: str = "fiscaldata",
    ust_force_refresh: bool = False,
    # Tagging
    spreadover_package_type: str = "MATCHED_MATURITY",
    only_tag_outrights: bool = True,
) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()

    # Apply outright mask if requested
    if only_tag_outrights and package_col in out.columns:
        outright_mask = out[package_col].fillna("OUTRIGHT").astype("string").values == "OUTRIGHT"
    else:
        outright_mask = np.ones(len(out), dtype=bool)

    # Match swaps to UST by maturity
    out = _match_swaps_to_ust_by_maturity(
        out,
        swap_maturity_col=swap_maturity_col,
        product_col=product_col,
        product_values=product_values,
        currency_col=currency_col,
        require_usd=require_usd,
        usd_value=usd_value,
        ust_ref_source=ust_ref_source,
        ust_force_refresh=ust_force_refresh,
    )

    # Tag matched trades
    can_tag = out["matched_ust_maturity"].fillna(False).values & outright_mask
    if can_tag.any():
        if package_col not in out.columns:
            out[package_col] = "OUTRIGHT"
        if "package_id" not in out.columns:
            out["package_id"] = None
        if "package_legs" not in out.columns:
            out["package_legs"] = None

        # Generate package IDs
        if trade_id_col in out.columns:
            pid = out.loc[can_tag, trade_id_col].astype("string").radd(f"{spreadover_package_type}_")
        else:
            pid = pd.Series(out.index[can_tag], index=out.index[can_tag]).astype("string").radd(f"{spreadover_package_type}_")

        out.loc[can_tag, package_col] = spreadover_package_type
        out.loc[can_tag, "package_id"] = pid.values

        # Package legs (swap leg only - bond leg is not in SDR)
        if trade_id_col in out.columns:
            out.loc[can_tag, "package_legs"] = out.loc[can_tag, trade_id_col].apply(lambda x: [int(x)] if pd.notna(x) else None).values
        else:
            out.loc[can_tag, "package_legs"] = out.index[can_tag].to_series().apply(lambda x: [int(x)]).values

    def _to_bool(x) -> bool:
        if isinstance(x, bool):
            return x
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return False
        return str(x).strip().lower() in {"true", "t", "1", "yes", "y"}

    def _split_parts(x):
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return []
        return [p.strip() for p in re.split(r"\s*/\s*", str(x).strip()) if p.strip()]

    def _mmdd(x):
        t = pd.to_datetime(x, errors="coerce")
        if pd.isna(t):
            return None
        return int(t.month), int(t.day)

    def _all_exp_same_mmdd(expiration_val, effective_val) -> bool:
        """
        True if ALL expiration dates (supports scalar Timestamp/date or 'a / b / c' string)
        have the same (month, day) as the effective date.
        """
        eff_md = _mmdd(effective_val)
        if eff_md is None:
            return False

        # scalar timestamp/date
        if isinstance(expiration_val, (pd.Timestamp, np.datetime64)) or hasattr(expiration_val, "year"):
            exp_mds = [_mmdd(expiration_val)]
        else:
            parts = _split_parts(expiration_val)
            exp_mds = [_mmdd(p) for p in parts] if parts else [_mmdd(expiration_val)]

        exp_mds = [md for md in exp_mds if md is not None]
        return bool(exp_mds) and all(md == eff_md for md in exp_mds)

    matched = out["matched_ust_maturity"].map(_to_bool)

    # Spot detection (T+2 busdays, vectorized)
    exec_ts = pd.to_datetime(out["execution_timestamp"], utc=True, errors="coerce").dt.tz_convert(None).dt.normalize()
    eff_ts = pd.to_datetime(out["effective_date"], errors="coerce").dt.normalize()
    m = exec_ts.notna() & eff_ts.notna()

    cal = USFederalHolidayCalendar()
    hol = cal.holidays(
        start=(exec_ts[m].min() - pd.Timedelta(days=10)),
        end=(exec_ts[m].max() + pd.Timedelta(days=30)),
    ).to_numpy(dtype="datetime64[D]")

    bdcal = np.busdaycalendar(holidays=hol)
    exec_days = exec_ts[m].to_numpy(dtype="datetime64[D]")
    spot_days = np.busday_offset(exec_days, 2, roll="forward", busdaycal=bdcal)
    spot_dt = pd.to_datetime(spot_days).normalize()

    spot_from_dates = pd.Series(False, index=out.index)
    spot_from_dates.loc[m] = eff_ts[m].to_numpy() == spot_dt.to_numpy()

    fwd = out["forward_label"] if "forward_label" in out.columns else pd.Series("", index=out.index)
    spot_from_label = fwd.astype(str).str.lower().eq("spot")
    is_spot = spot_from_dates | spot_from_label

    # Coincidental month/day roll (spot start + same MM-DD)
    same_mmdd = out.apply(
        lambda r: _all_exp_same_mmdd(r.get(swap_maturity_col), r.get("effective_date")),
        axis=1,
    )

    # NEW: short-dated swaps (< 1Y) are almost surely just spot-starting swaps, not matched-maturity spread trades
    ten_y = pd.to_numeric(out.get("tenor_years"), errors="coerce")
    short_by_tenor = ten_y.notna() & (ten_y < 1.0)

    # fallback if tenor_years missing: use date difference
    exp_ts = pd.to_datetime(out.get(swap_maturity_col), errors="coerce")
    short_by_dates = exp_ts.notna() & eff_ts.notna() & ((exp_ts.dt.normalize() - eff_ts).dt.days < 370)

    short_expiration = short_by_tenor | short_by_dates

    # LOW if matched + spot + (same MM-DD OR short expiration)
    low_conf = matched & is_spot & (same_mmdd | short_expiration)

    conf = pd.Series(pd.NA, index=out.index, dtype="string")
    conf.loc[matched] = "high"
    conf.loc[low_conf] = "low"
    out["matched_ust_maturity_trade_confidence"] = conf

    return out


def _match_swaps_to_ust_by_maturity(
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
    Add UST reference fields to swaps whose maturity matches a UST.

    Output columns (if matched):
    - ust_cusip, ust_oi, ust_security_type, ust_issue_date, ust_coupon, ...
    - matched_ust_maturity (bool)

    This is a *matched maturity* join. It does NOT attempt "nearest on-the-run" mapping.
    """
    if df.empty:
        return df

    out = df.copy()

    # Identify candidate swaps
    m = out[product_col].isin(list(product_values)).values
    if require_usd and currency_col in out.columns:
        m &= out[currency_col].astype("string").values == usd_value

    if not m.any():
        out["matched_ust_maturity"] = False
        return out

    # Load and build maturity map
    ust_ref = _load_ust_reference_data(source=ust_ref_source, force_refresh=ust_force_refresh)
    maturity_map = _build_maturity_to_ust_map(ust_ref)

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

    # Copy UST fields
    for c in [c for c in tmp.columns if c.startswith("ust_")]:
        out.loc[idx, c] = tmp[c].values

    # Record the swap maturity date used
    out.loc[idx, "swap_maturity_date"] = tmp["_swap_maturity_date"].values

    return out


class MatchedMaturityPackageDetector(PackageDetector):
    """
    Package detector for swap/UST matched maturity spreads.

    Identifies swaps that mature on UST maturity dates,
    """

    package_type = PACKAGE_TYPES.MMS

    def detect(self, df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """Detect MMS packages in the DataFrame."""
        return detect_mms_trades_df(df, **kwargs)
