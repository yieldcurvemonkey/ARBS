from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import QuantLib as ql

# fmt: off
import Query.IRSwaps.adapter  # noqa: F401
# fmt: on

from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from SDRUtils.core.classification import TradeClassification, classify_product_type
from SDRUtils.core.utils import (
    _ensure_int64_epoch_seconds,
    _parse_notional,
    _pv01_bucket,
    _to_ql_date,
    calculate_forward_start_years,
    calculate_tenor_years,
    forward_to_label,
    tenor_to_label,
    _USD_OIS_CAL,
)
from SDRUtils.products.base import ProductModule
from SDRUtils.registry import registry


def classify_sofr_swap_trade(row: pd.Series, trade_id: int, curve: _IRSwapGenericCurve) -> TradeClassification:
    """Classify a single SDR trade"""

    execution_ts = pd.to_datetime(row.get("Execution Timestamp"))
    effective_date = pd.to_datetime(row.get("Effective Date"))
    expiration_date = pd.to_datetime(row.get("Expiration Date"))

    product_type = classify_product_type(row)

    # 1. Calculate Tenor
    tenor_years = calculate_tenor_years(effective_date, expiration_date)

    # UPDATED: Pass expiration_date to capture IMM/FOMC labels on the back leg
    tenor_label = tenor_to_label(tenor_years, expiration_date=expiration_date)

    # 2. Calculate Forward/Spot status
    forward_years = calculate_forward_start_years(execution_ts, effective_date)

    ql_exec = _to_ql_date(execution_ts)
    ql_eff = _to_ql_date(effective_date)

    is_forward = False
    if ql_exec and ql_eff:
        t_plus_2 = _USD_OIS_CAL.advance(ql_exec, 2, ql.Days)
        if ql_eff > t_plus_2:
            is_forward = True

    forward_label = forward_to_label(forward_years, effective_date=effective_date)

    # 3. Build Trade Label
    # If either leg is "Special" (IMM/FOMC), we use the full description
    is_special_forward = forward_label.startswith("IMM_") or forward_label.startswith("FOMC_")

    if is_forward or is_special_forward:
        trade_label = f"{forward_label} {tenor_label}"
    else:
        trade_label = f"spot {tenor_label}"

    notional = _parse_notional(row.get("Notional amount-Leg 1", 0))
    fixed_rate = row.get("Fixed rate-Leg 1")
    strike = row.get("Strike Price")

    pkg, _ = IRSwapQuery(
        curve="USD-SOFR-1D", effective_date=effective_date.date(), maturity_date=expiration_date.date(), structure_kwargs={"notional": notional}
    ).resolve_package(pricer_or_curve=curve)
    pv01 = curve.pv01(pkg[0])

    return TradeClassification(
        trade_id=trade_id,
        execution_timestamp=execution_ts,
        effective_date=effective_date,
        expiration_date=expiration_date,
        product_type=product_type,
        tenor_years=tenor_years,
        tenor_label=tenor_label,
        is_forward=is_forward,
        forward_start_years=forward_years,
        forward_label=forward_label,
        trade_label=trade_label,
        notional=notional,
        notional_currency=row.get("Notional currency-Leg 1", "USD"),
        fixed_rate=fixed_rate if pd.notna(fixed_rate) else None,
        strike=strike if pd.notna(strike) else None,
        estimated_pv01=pv01,
        package_type="OUTRIGHT",
    )


class USD_SOFR_SwapProduct(ProductModule):
    name = "USD-SOFR-OIS"
    product_type = "OIS_SWAP"

    def classify_trade(self, row: pd.Series, trade_id: int, **kwargs) -> TradeClassification:
        curve = kwargs.get("curve")
        if curve is None:
            raise ValueError("USD_SOFR_SwapProduct requires a 'curve' keyword argument.")
        return classify_sofr_swap_trade(row, trade_id, curve)

    def classify_product_type(self, row: pd.Series) -> str:
        return classify_product_type(row)


registry.register_product(USD_SOFR_SwapProduct())


def detect_ust_mms_trades_df(
    df: pd.DataFrame,
    *,
    # swap columns
    product_col: str = "product_type",
    product_values: Sequence[str] = ("OIS_SWAP",),
    package_col: str = "package_type",
    trade_id_col: str = "trade_id",
    swap_maturity_col: str = "expiration_date",
    currency_col: str = "notional_currency",
    require_usd: bool = True,
    usd_value: str = "USD",
    # ust ref
    ust_ref_source: str = "fiscaldata",
    ust_force_refresh: bool = False,
    # tagging
    spreadover_package_type: str = "SPREADOVER",
    only_tag_outrights: bool = True,
) -> pd.DataFrame:

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
        Adds UST reference fields to swaps whose maturity date exactly matches a UST maturity_date.

        Output columns (if matched):
        - ust_cusip, ust_oi, ust_security_type, ust_issue_date, ust_coupon, ...
        - matched_ust_maturity (bool)

        This is a *matched maturity* join. It does NOT attempt “nearest on-the-run” mapping.
        """

        def _load_ust_reference_data(
            *,
            source: str = "fiscaldata",
            force_refresh: bool = False,
        ) -> pd.DataFrame:
            from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import update_reference_data

            ref = update_reference_data(source=source, force_refresh=force_refresh).copy()

            # normalize key fields
            if "maturity_date" in ref.columns:
                ref["maturity_date"] = pd.to_datetime(ref["maturity_date"], errors="coerce").dt.date
            if "issue_date" in ref.columns:
                ref["issue_date"] = pd.to_datetime(ref["issue_date"], errors="coerce").dt.date

            return ref

        def _build_maturity_to_ust_map(
            ust_ref: pd.DataFrame,
            *,
            prefer_oi: Optional[Sequence[str]] = None,  # e.g. ("2-Year","3-Year","5-Year","7-Year","10-Year","20-Year","30-Year")
        ) -> pd.DataFrame:
            """
            Returns 1 row per maturity_date, choosing a "best" CUSIP:
            - prefer latest issue_date (reopenings share maturity)
            - deterministic tie-breaks
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
            # deterministic tie-breakers
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

        if df.empty:
            return df

        out = df.copy()

        # candidate swaps
        m = out[product_col].isin(list(product_values)).values
        if require_usd and currency_col in out.columns:
            m &= out[currency_col].astype("string").values == usd_value

        if not m.any():
            # still ensure columns exist for downstream code
            out["matched_ust_maturity"] = False
            return out

        # load + build maturity map
        ust_ref = _load_ust_reference_data(source=ust_ref_source, force_refresh=ust_force_refresh)
        maturity_map = _build_maturity_to_ust_map(ust_ref)

        def _to_date_series(x: pd.Series) -> pd.Series:
            # Works for datetime64[ns], Timestamp w/ tz, python date, strings
            return pd.to_datetime(x, errors="coerce", utc=True).dt.date

        # normalize swap maturity date
        swap_mat = _to_date_series(out.loc[m, swap_maturity_col])
        tmp = out.loc[m, ["trade_id"]].copy() if "trade_id" in out.columns else out.loc[m, []].copy()
        tmp["_swap_maturity_date"] = swap_mat.values

        # merge
        tmp = tmp.merge(
            maturity_map,
            left_on="_swap_maturity_date",
            right_on="maturity_date",
            how="left",
        )

        # write back (vectorized)
        out["matched_ust_maturity"] = False
        matched = tmp["ust_cusip"].notna().values

        # align index positions of m==True rows
        idx = out.index[m]
        out.loc[idx, "matched_ust_maturity"] = matched

        # bring UST fields back
        for c in [c for c in tmp.columns if c.startswith("ust_")]:
            out.loc[idx, c] = tmp[c].values

        # optional: also record the swap maturity date used for join
        out.loc[idx, "swap_maturity_date"] = tmp["_swap_maturity_date"].values

        return out

    if df.empty:
        return df

    out = df.copy()

    # optional: only re-tag OUTRIGHT rows
    if only_tag_outrights and package_col in out.columns:
        outright_mask = out[package_col].fillna("OUTRIGHT").astype("string").values == "OUTRIGHT"
    else:
        outright_mask = np.ones(len(out), dtype=bool)

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

    # tag
    can_tag = out["matched_ust_maturity"].fillna(False).values & outright_mask
    if can_tag.any():
        if package_col not in out.columns:
            out[package_col] = "OUTRIGHT"
        if "package_id" not in out.columns:
            out["package_id"] = None
        if "package_legs" not in out.columns:
            out["package_legs"] = None

        # package_id: deterministic, no loops
        # If trade_id missing, fall back to index
        if trade_id_col in out.columns:
            pid = out.loc[can_tag, trade_id_col].astype("string").radd("SPREADOVER_")
        else:
            pid = pd.Series(out.index[can_tag], index=out.index[can_tag]).astype("string").radd("SPREADOVER_")

        out.loc[can_tag, package_col] = spreadover_package_type
        out.loc[can_tag, "package_id"] = pid.values

        # package_legs: swap leg only (bond leg is not in SDR swaps df)
        if trade_id_col in out.columns:
            out.loc[can_tag, "package_legs"] = out.loc[can_tag, trade_id_col].apply(lambda x: [int(x)] if pd.notna(x) else None).values
        else:
            out.loc[can_tag, "package_legs"] = out.index[can_tag].to_series().apply(lambda x: [int(x)]).values

    return out
