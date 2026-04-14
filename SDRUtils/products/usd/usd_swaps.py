"""
USD swap product module.

Provides classification and analysis for USD OIS and USD fixed-float swaps
reported to the DTCC SDR.
"""

from __future__ import annotations

import datetime
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytz
import QuantLib as ql
import requests
from tqdm import tqdm

import Query.IRSwaps.adapter  # noqa: F401
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps._CME_INVOICE_SWAP_TICKERS import _CME_INVOICE_SWAP_TICKERS, _INDICATOR_TO_TICKER
from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from SDRUtils.config import PRODUCT_TYPES, TRADE_ID, USD_CONVENTIONS
from SDRUtils.core.classification import SwapTradeClassification, classifications_to_dataframe, classify_product_type
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years, to_ql_date
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import build_trade_label, classify_intrinsic_special_tenor, forward_to_label, tenor_from_dates, tenor_to_label
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.packages.curve import detect_curve_trades_df
from SDRUtils.packages.fly import detect_fly_trades_df
from SDRUtils.packages.mms import detect_mms_trades_df
from SDRUtils.products._swaps._cme_mac import fetch_mac_ref_data
from SDRUtils.products._swaps.filters import (
    is_usd_swap,
    new_usd_swap_trades,
    usd_swap_trades,
)
from SDRUtils.products.usd.base import USDProductBase
from SDRUtils.packages.utils import merge_package_legs_to_one_row
from SDRUtils.products.usd.upi_classifier import classify_rate_index
from SDRUtils.products.usd.linear_base import LinearProductType
from SDRUtils.products.usd.sofr_ois import classify_sofr_ois_trade
from SDRUtils.products.usd.fed_funds_ois import classify_fed_funds_ois_trade
from SDRUtils.products.usd.basis_swaps import classify_basis_swap_trade


def classify_usd_swap_trade(
    row: pd.Series,
    trade_id: int,
    curve: _IRSwapGenericCurve,
) -> SwapTradeClassification:
    """
    Classify a single USD swap trade from SDR data.

    This function extracts all relevant trade characteristics:
    - Product type (OIS_SWAP, SWAPTION, etc.)
    - Tenor and forward start calculations
    - Special date detection (IMM/FOMC)
    - PV01 calculation (if curve provided)

    Args:
        row: SDR data row as pandas Series
        trade_id: Unique identifier for the trade
        curve: Optional curve object for PV01 calculation

    Returns:
        SwapTradeClassification object with all trade details
    """
    # Extract dates
    execution_ts = pd.to_datetime(row.get("Execution Timestamp"))
    effective_date = pd.to_datetime(row.get("Effective Date"))
    expiration_date = pd.to_datetime(row.get("Expiration Date"))

    # Determine product type
    product_type = classify_product_type(row)

    # Calculate tenor
    tenor_years = calculate_tenor_years(
        effective_date,
        expiration_date,
        conventions=USD_CONVENTIONS,
    )
    tenor_label = tenor_from_dates(effective_date, expiration_date)

    # Calculate forward start
    forward_years = calculate_forward_start_years(
        execution_ts,
        effective_date,
        conventions=USD_CONVENTIONS,
    )

    # Determine if forward-starting using T+2 convention
    ql_exec = to_ql_date(execution_ts)
    ql_eff = to_ql_date(effective_date)

    is_forward = False
    if ql_exec and ql_eff:
        t_plus_2 = USD_CONVENTIONS.calendar.advance(ql_exec, 2, ql.Days)
        if ql_eff > t_plus_2:
            is_forward = True

    forward_label = forward_to_label(forward_years, effective_date=effective_date)

    # Build trade label
    trade_label = build_trade_label(forward_label, tenor_label, is_forward)

    # Phase 1: intrinsic special tenor classification
    special_tenor_type, special_tenor_confidence, special_tenor_tags = classify_intrinsic_special_tenor(
        effective_date=effective_date,
        expiration_date=expiration_date,
        tenor_label=tenor_label,
        forward_label=forward_label,
        is_forward=is_forward,
    )

    # Extract notional and rate
    notional, is_notional_capped = parse_notional(row.get("Notional amount-Leg 1", row.get("Notional amount-Leg 2", 0)))
    fixed_rate = row.get("Fixed rate-Leg 1", row.get("Fixed rate-Leg 2"))
    # Keep the existing SOFR curve approximation for all USD swap underliers.
    pv01 = float("nan")
    if curve is not None and pd.notna(effective_date) and pd.notna(expiration_date):
        try:
            pkg, _ = IRSwapQuery(
                curve="USD-SOFR-1D",
                effective_date=effective_date.date(),
                maturity_date=expiration_date.date(),
                structure_kwargs={"notional": notional},
            ).resolve_package(pricer_or_curve=curve)
            if pkg:
                pv01 = curve.pv01(pkg[0])
        except Exception:
            pv01 = float("nan")

    return SwapTradeClassification(
        event_action=f"{row.get('Action type')}-{row.get('Event type')}",
        trade_id=trade_id,
        execution_timestamp=execution_ts,
        effective_date=effective_date,
        expiration_date=expiration_date,
        product_type=product_type,
        trade_label=trade_label,
        tenor_years=tenor_years,
        tenor_label=tenor_label,
        is_forward=is_forward,
        forward_start_years=forward_years,
        forward_label=forward_label,
        notional=notional,
        notional_currency=row.get("Notional currency-Leg 1", "USD"),
        is_notional_capped=is_notional_capped,
        fixed_rate=fixed_rate if pd.notna(fixed_rate) else None,
        estimated_pv01=pv01,
        package_type="OUTRIGHT",
        special_tenor_type=special_tenor_type,
        special_tenor_confidence=special_tenor_confidence,
        special_tenor_tags=special_tenor_tags,
    )


def detect_invoice_swaps(
    package_df: pd.DataFrame,
    execution_col: str = "execution_timestamp",
    effective_col: str = "effective_date",
    maturity_col: str = "expiration_date",
    confidence_col: Optional[str] = "matched_ust_maturity_trade_confidence",
    require_high_confidence: bool = True,
    output_col: str = "invoice_swap_ticker",
    show_tqdm: bool = True,
) -> pd.DataFrame:
    """
    Match trades against CME invoice-swap CTD specs and annotate with ticker.

    Defaults are the USD swap mapping keys:
    - start date: effective_date
    - maturity date: expiration_date

    Callers can override these keys for other products (for example swaptions
    where maturity matching is done on underlying_expiration_date).
    """
    if package_df.empty:
        return package_df

    out = package_df.copy()
    if execution_col not in out.columns:
        if output_col not in out.columns:
            out[output_col] = None
        return out

    exec_dates = pd.to_datetime(out[execution_col], errors="coerce")
    if exec_dates.isna().all():
        if output_col not in out.columns:
            out[output_col] = None
        return out

    as_of = exec_dates.dt.date.value_counts().index[0]
    lookup = _build_invoice_swap_lookup(as_of=as_of, show_tqdm=show_tqdm)
    return _apply_invoice_swap_lookup(
        out,
        lookup,
        effective_col=effective_col,
        maturity_col=maturity_col,
        confidence_col=confidence_col,
        require_high_confidence=require_high_confidence,
        output_col=output_col,
    )


def _build_invoice_swap_lookup(
    *,
    as_of: datetime.date,
    show_tqdm: bool = True,
) -> pd.DataFrame:
    """Build a unique lookup table: (delivery_date, ctd_maturity) -> invoice ticker."""
    from definitions.USTFutures import front_month
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

    ustf_mdp = USTFuturesMDP(source="BARCHART_USTF-RL")
    roots = sorted({spec["root"] for spec in _CME_INVOICE_SWAP_TICKERS.values()})
    invoice_specs = []
    iterator = tqdm(roots, desc="FETCHING DELIVERY BASKETS...") if show_tqdm else roots
    for root in iterator:
        contract = front_month(as_of, root)

        try:
            basket = ustf_mdp.get_delivery_basket(as_of=as_of, symbol=contract, usts_mdp_source="USTS_FEDINVEST_WSJ_LIVE-RL")
        except Exception:
            try:
                basket = ustf_mdp.get_delivery_basket(as_of=as_of, symbol=contract, usts_mdp_source="USTS_TRADINGVIEW_LIVE-RL")
            except Exception:
                continue

        try:
            delivery_start, delivery_end = basket["delivery"]
        except Exception:
            continue

        try:
            pricer = ustf_mdp.get_pricer(request={"symbols": [contract], "timestamp": as_of, "usts_mdp_source": "USTS_FEDINVEST_WSJ_LIVE-RL"})[contract]
        except Exception:
            try:
                pricer = ustf_mdp.get_pricer(request={"symbols": [contract], "timestamp": as_of, "usts_mdp_source": "USTS_TRADINGVIEW_LIVE-RL"})[contract]
            except Exception:
                continue

        for indicator in "ABCDEF":
            ticker = _INDICATOR_TO_TICKER.get(root, {}).get(indicator)
            if not ticker:
                continue
            delivery_date = delivery_end if _CME_INVOICE_SWAP_TICKERS[ticker]["delivery"] == "last" else delivery_start
            try:
                ctd_pricer = pricer.ctd(indicator)
            except Exception:
                # Invoice enrichment is best-effort and must never break ingestion.
                continue
            if ctd_pricer is None:
                continue
            invoice_specs.append(
                {
                    "invoice_swap_delivery_date": delivery_date,
                    "invoice_swap_ctd_maturity": ctd_pricer.maturity_date(),
                    "invoice_swap_ticker": ticker,
                }
            )

    if not invoice_specs:
        return pd.DataFrame(columns=["invoice_swap_delivery_date", "invoice_swap_ctd_maturity", "invoice_swap_ticker"])

    lookup = pd.DataFrame(invoice_specs).drop_duplicates(subset=["invoice_swap_delivery_date", "invoice_swap_ctd_maturity"], keep="first")
    lookup["invoice_swap_delivery_date"] = pd.to_datetime(lookup["invoice_swap_delivery_date"])
    lookup["invoice_swap_ctd_maturity"] = pd.to_datetime(lookup["invoice_swap_ctd_maturity"])
    return lookup


def _apply_invoice_swap_lookup(
    package_df: pd.DataFrame,
    lookup: pd.DataFrame,
    *,
    effective_col: str,
    maturity_col: str,
    confidence_col: Optional[str],
    require_high_confidence: bool,
    output_col: str,
) -> pd.DataFrame:
    out = package_df.copy()

    if output_col not in out.columns:
        out[output_col] = None

    if lookup.empty:
        return out
    if effective_col not in out.columns or maturity_col not in out.columns:
        return out

    out[effective_col] = pd.to_datetime(out[effective_col], errors="coerce")
    out[maturity_col] = pd.to_datetime(out[maturity_col], errors="coerce")

    maturity_norm_col = f"__{maturity_col}_norm"
    out[maturity_norm_col] = out[maturity_col].dt.normalize()

    df_invoice_subset = lookup[["invoice_swap_delivery_date", "invoice_swap_ctd_maturity", "invoice_swap_ticker"]].rename(
        columns={"invoice_swap_ticker": "__invoice_swap_ticker_new"}
    )
    df_merged = out.merge(
        df_invoice_subset,
        left_on=[effective_col, maturity_norm_col],
        right_on=["invoice_swap_delivery_date", "invoice_swap_ctd_maturity"],
        how="left",
    )

    condition = df_merged["__invoice_swap_ticker_new"].notna()
    if require_high_confidence and confidence_col and confidence_col in df_merged.columns:
        condition &= df_merged[confidence_col].astype("string").str.lower().eq("high")

    df_merged.loc[condition, output_col] = df_merged.loc[condition, "__invoice_swap_ticker_new"]

    cols_to_drop = [
        maturity_norm_col,
        "__invoice_swap_ticker_new",
        "invoice_swap_delivery_date",
        "invoice_swap_ctd_maturity",
        "invoice_swap_delivery_date_y",
        "invoice_swap_ctd_maturity_y",
    ]
    existing_cols_to_drop = [c for c in df_merged.columns if c in cols_to_drop]
    return df_merged.drop(columns=existing_cols_to_drop, errors="ignore")


def detect_mac_swaps(package_df: pd.DataFrame) -> pd.DataFrame:
    out = package_df.copy()

    out["_mac_eff"] = pd.to_datetime(out.get("effective_date"), errors="coerce").dt.normalize()
    out["_mac_exp"] = pd.to_datetime(out.get("expiration_date"), errors="coerce").dt.normalize()
    out["_fixed_rate"] = pd.to_numeric(out.get("fixed_rate"), errors="coerce")
    out["_fixed_rate_bp"] = (out["_fixed_rate"] * 10000).round().astype("Int64")

    mac_lookup_frames: list[pd.DataFrame] = []
    mac_cache: dict[tuple[int, int], pd.DataFrame] = {}

    for eff in out["_mac_eff"].dropna().unique():
        key = (int(eff.year), int(eff.month))
        if key not in mac_cache:
            try:
                mac_cache[key] = fetch_mac_ref_data(effective_date=eff)
            except Exception:
                mac_cache[key] = pd.DataFrame()
        if not mac_cache[key].empty:
            mac_lookup_frames.append(mac_cache[key])

    if not mac_lookup_frames:
        out["is_mac"] = False
        return out.drop(columns=["_mac_eff", "_mac_exp", "_fixed_rate", "_fixed_rate_bp"], errors="ignore")

    mac_lookup = pd.concat(mac_lookup_frames, ignore_index=True)
    mac_lookup = mac_lookup.dropna(subset=["imm_start_date", "expiration_date", "coupon"]).copy()

    mac_lookup["_mac_eff"] = pd.to_datetime(mac_lookup["imm_start_date"], errors="coerce").dt.normalize()
    mac_lookup["_mac_exp"] = pd.to_datetime(mac_lookup["expiration_date"], errors="coerce").dt.normalize()
    mac_lookup["_mac_coupon"] = pd.to_numeric(mac_lookup["coupon"], errors="coerce") / 100.0
    mac_lookup["_mac_coupon_bp"] = (mac_lookup["_mac_coupon"] * 10000).round().astype("Int64")

    mac_lookup = mac_lookup[["_mac_eff", "_mac_exp", "_mac_coupon_bp"]].drop_duplicates()

    tol_days = 5
    exp_lists = mac_lookup.groupby(["_mac_eff", "_mac_coupon_bp"])["_mac_exp"].apply(lambda s: tuple(pd.Series(s).dropna().unique())).to_dict()

    def _row_is_mac(eff, exp, coupon_bp) -> bool:
        if pd.isna(eff) or pd.isna(exp) or pd.isna(coupon_bp):
            return False
        exps = exp_lists.get((eff, int(coupon_bp)))
        if not exps:
            return False
        exp = pd.Timestamp(exp)
        for mexp in exps:
            if abs((exp - pd.Timestamp(mexp)).days) <= tol_days:
                return True
        return False

    # out["is_mac"] = [_row_is_mac(eff, exp, cpn) for eff, exp, cpn in zip(out["_mac_eff"].values, out["_mac_exp"].values, out["_fixed_rate_bp"].values)]
    out["is_mac"] = [
        _row_is_mac(eff, exp, cpn)
        for eff, exp, cpn in tqdm(
            zip(out["_mac_eff"].values, out["_mac_exp"].values, out["_fixed_rate_bp"].values),
            total=len(out),
            desc="Detecting MAC swaps",
            leave=False,
        )
    ]

    return out.drop(columns=["_mac_eff", "_mac_exp", "_fixed_rate", "_fixed_rate_bp"], errors="ignore")


def detect_spreadovers(package_df: pd.DataFrame):
    copy_df = package_df.copy()

    broker_spreadover_mask = (
        (copy_df["package_legs"].isna())
        & (copy_df["package_indicator"] == True)
        & (copy_df["package_transaction_spread"].notna())
        # & (copy_df["package_transaction_spread"] != "")
        & (copy_df["forward_label"] == "spot")
    )
    copy_df["is_spreadover"] = False
    copy_df.loc[broker_spreadover_mask, "is_spreadover"] = True

    asset_swap_mask = (
        (copy_df["package_legs"].isna())
        & (copy_df["package_indicator"] == True)
        & (copy_df["package_transaction_spread"].notna())
        & (copy_df["other_payment_type"] == "UFRO")
        & (copy_df["forward_label"] == "spot")
    )
    copy_df["is_asset_swap"] = False
    copy_df.loc[asset_swap_mask, "is_asset_swap"] = True

    return copy_df


def _coerce_numeric_like(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")

    normalized = (
        series.astype("string")
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    )
    normalized = normalized.where(~normalized.isin(["", "None", "none", "nan", "NaN"]), other=pd.NA)
    return pd.to_numeric(normalized, errors="coerce")


def _is_round_notional(notional: float, threshold: float = 5_000_000) -> bool:
    """True if notional is a 'round' number (divisible by threshold with no remainder)."""
    if pd.isna(notional) or notional <= 0:
        return False
    return (notional % threshold) == 0


def _resolve_special_tenor_priority(df: pd.DataFrame) -> pd.DataFrame:
    """
    After all detectors have run, resolve unified special_tenor fields.

    Reads existing detection columns (matched_ust_maturity, invoice_swap_ticker,
    is_mac) and merges them with Phase 1 intrinsic tags. Applies priority
    hierarchy and round-notional confidence adjustment.

    Priority (lowest to highest):
        STANDARD < IMM < FOMC < MAC < MATCHED_MATURITY < INVOICE_SWAP
    """
    from SDRUtils.config import SPECIAL_TENOR_PRIORITY

    out = df.copy()

    if out.empty:
        return out

    priority_map = {t: i for i, t in enumerate(SPECIAL_TENOR_PRIORITY)}

    def _parse_tags(val) -> list[str]:
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if not inner:
                    return []
                return [t.strip().strip("'\"") for t in inner.split(",")]
            return [val] if val else []
        return []

    def _resolve_row(row):
        tags = list(_parse_tags(row.get("special_tenor_tags", [])))
        intrinsic_type = str(row.get("special_tenor_type", "STANDARD"))

        # Collect Phase 2 detections
        if row.get("matched_ust_maturity") is True or str(row.get("matched_ust_maturity")).lower() == "true":
            if "MATCHED_MATURITY" not in tags:
                tags.append("MATCHED_MATURITY")

        if pd.notna(row.get("invoice_swap_ticker")) and str(row.get("invoice_swap_ticker")).strip():
            if "INVOICE_SWAP" not in tags:
                tags.append("INVOICE_SWAP")

        if row.get("is_mac") is True or str(row.get("is_mac")).lower() == "true":
            if "MAC" not in tags:
                tags.append("MAC")

        # Determine primary type by priority
        if not tags:
            return "STANDARD", "high", []

        primary = max(tags, key=lambda t: priority_map.get(t, -1))

        # Confidence scoring for MATCHED_MATURITY
        conf = "high"
        if primary in ("MATCHED_MATURITY", "INVOICE_SWAP"):
            fwd = str(row.get("forward_label", "spot")).strip().lower()
            is_spot = fwd == "spot"
            notional = pd.to_numeric(row.get("notional"), errors="coerce")
            tenor_y = pd.to_numeric(row.get("tenor_years"), errors="coerce")

            if pd.notna(tenor_y) and tenor_y < 1.0:
                conf = "low"
            elif is_spot:
                if _is_round_notional(notional if pd.notna(notional) else 0):
                    conf = "low"
                else:
                    conf = "medium"
            # Forward-starting or invoice: keep "high"

        return primary, conf, tags

    results = out.apply(_resolve_row, axis=1, result_type="expand")
    results.columns = ["special_tenor_type", "special_tenor_confidence", "special_tenor_tags"]
    out["special_tenor_type"] = results["special_tenor_type"]
    out["special_tenor_confidence"] = results["special_tenor_confidence"]
    out["special_tenor_tags"] = results["special_tenor_tags"]

    return out


def _prepare_cache_dataframe_for_arrow(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    numeric_columns = [
        "notional",
        "tenor_years",
        "forward_start_years",
        "fixed_rate",
        "estimated_pv01",
        "package_transaction_spread",
        "other_payment_amount",
    ]
    for col in numeric_columns:
        if col in out.columns:
            out[col] = _coerce_numeric_like(out[col])
    return out


def _risk_from_estimated_pv01(value: Any) -> float:
    try:
        if isinstance(value, str):
            return float(value.split("/")[0])
        return float(value)
    except Exception:
        return float("nan")


def _classify_messages_v2(
    messages: pd.DataFrame,
    exec_date=None,
    curve_source: str = "ERIS_EOD_LIVE-RL_BASIC",
    **kwargs,
):
    """
    V2 classification: routes trades through SOFR/FF/basis classifiers
    with segment-appropriate DV01 curves.

    Short-end (<=3Y): BARCHART_STIRF-RL
    Medium-term (>3Y): ERIS_EOD_LIVE-RL_BASIC
    """
    import logging

    logger = logging.getLogger(__name__)

    filtered = messages[
        (messages["Action type"] == "NEWT") & (messages["Event type"] == "TRAD")
    ].copy()

    if filtered.empty:
        return []

    # Lazy-load curves per segment (only when needed)
    _curves = {}

    def _get_curve(segment_key: str):
        if segment_key not in _curves:
            try:
                if segment_key == "SHORT":
                    src = kwargs.get("short_curve_source", "BARCHART_STIRF-RL")
                    mdp = IRSwapsMDP(source=src)
                else:
                    src = kwargs.get("medium_curve_source", curve_source)
                    mdp = IRSwapsMDP(source=src)
                _curves[segment_key] = mdp.get_pricer(dict(
                    curve_name="USD-SOFR-1D", timestamp=exec_date,
                ))
            except Exception as e:
                logger.warning(f"Failed to load {segment_key} curve: {e}")
                _curves[segment_key] = None
        return _curves[segment_key]

    classifications = []

    for _, row in tqdm(filtered.iterrows(), desc="V2 Classifying", unit="trade", total=len(filtered)):
        trade_id = row.get(TRADE_ID)
        try:
            upi = classify_rate_index(
                row.get("UPI Underlier Name"),
                row.get("UPI FISN"),
            )

            if upi.product_type == LinearProductType.BASIS:
                c = classify_basis_swap_trade(row, trade_id=trade_id)
            elif upi.rate_index is not None and "FED_FUNDS" in upi.rate_index.value:
                c = classify_fed_funds_ois_trade(row, trade_id=trade_id)
            elif upi.rate_index is not None:
                c = classify_sofr_ois_trade(row, trade_id=trade_id)
            else:
                # Fallback to V1 classifier
                curve = _get_curve("MEDIUM")
                c = classify_usd_swap_trade(row, trade_id=trade_id, curve=curve)

            # Compute PV01 with segment-appropriate curve if not already set
            if hasattr(c, 'tenor_segment') and c.tenor_segment is not None:
                seg = c.tenor_segment.value if hasattr(c.tenor_segment, 'value') else str(c.tenor_segment)
                curve = _get_curve(seg)
            else:
                curve = _get_curve("MEDIUM")

            if curve is not None and c.estimated_pv01 is None:
                try:
                    pkg, _ = IRSwapQuery(
                        curve="USD-SOFR-1D",
                        effective_date=c.effective_date.date() if hasattr(c.effective_date, 'date') else c.effective_date,
                        maturity_date=c.expiration_date.date() if hasattr(c.expiration_date, 'date') else c.expiration_date,
                        structure_kwargs={"notional": c.notional or 1_000_000},
                    ).resolve_package(pricer_or_curve=curve)
                    if pkg:
                        c.estimated_pv01 = curve.pv01(pkg[0])
                except Exception:
                    pass

            classifications.append(c)
        except Exception as e:
            logger.error(f"V2 classification failed for {trade_id}: {e}")

    return classifications


class USD_SwapProduct(USDProductBase):
    """
    USD swap product implementation.

    This class implements the ProductModule interface for USD swaps,
    providing trade classification and product type inference.
    """

    name = "USD-SWAPS"
    product_type = PRODUCT_TYPES.OIS_SWAP

    def classify_trade(self, row: pd.Series, trade_id: int, curve: _IRSwapGenericCurve) -> SwapTradeClassification:
        """
        Classify a single USD swap trade.

        Args:
            row: SDR data row
            trade_id: Trade identifier
            **kwargs: Additional arguments, including 'curve' for PV01

        Returns:
            SwapTradeClassification object
        """
        return classify_usd_swap_trade(
            row,
            trade_id,
            curve,
        )

    def classify_product_type(self, row: pd.Series) -> str:
        """Infer product type from SDR row."""
        return classify_product_type(row)

    def build_classification_dataframe(
        self,
        start: datetime.datetime,
        end: datetime.datetime,
        cache_path: str,
        detect_curve=True,
        detect_fly=True,
        detect_mms=True,
        detect_invoice=True,
        detect_mac=True,
        detect_spreadover=True,
        ignore_cache: bool = False,
        merge_package_legs: bool = False,
        use_v2_classification: bool = False,
        **kwargs: Any,
    ):
        sdr = SDRDataBuilder(cache_path=cache_path, show_tqdm=True)
        raw_sdr_trades_df = sdr.grab_sdr_trades(
            start_timestamp=start,
            end_timestamp=end,
            agency="CFTC",
            asset_class="RATES",
            filter_func=usd_swap_trades,
            ignore_cache=ignore_cache,
        )

        if raw_sdr_trades_df.empty:
            return raw_sdr_trades_df

        # TODO review needed
        # Execution Timestamp = Date and time a transaction was originally executed, resulting in the generation of a new UTI. This data element remains unchanged throughout the life of the UTI.
        # Event Timestamp = Date and time of occurrence of the event as determined by the reporting counterparty or a service provider
        # exec_dates = pd.to_datetime(raw_sdr_trades_df["Execution Timestamp"], errors="coerce").dt.date
        exec_dates = pd.to_datetime(raw_sdr_trades_df["Event timestamp"], errors="coerce").dt.date
        raw_sdr_trades_df = raw_sdr_trades_df.assign(_execution_date=exec_dates)

        curve_source = str(kwargs.get("curve_source", "ERIS_EOD_LIVE-RL_BASIC")).replace("/", "_")
        mdp = IRSwapsMDP(source=curve_source)

        cache_flags = f"curve{int(detect_curve)}_fly{int(detect_fly)}_mms{int(detect_mms)}_invoice{int(detect_invoice)}_mac{int(detect_mac)}_spreadover{int(detect_spreadover)}"
        cache_base = Path(cache_path) / "classification_cache" / "usd_swaps" / curve_source / cache_flags
        legacy_cache_base = Path(cache_path) / "classification_cache" / "usd_sofr_swaps" / curve_source / cache_flags
        cache_base.mkdir(parents=True, exist_ok=True)

        cached_frames = []
        missing_dates = []
        for exec_date, count in raw_sdr_trades_df["_execution_date"].value_counts().items():
            if pd.isna(exec_date):
                continue
            found_cache = False
            if ignore_cache is False:
                date_dirs = [
                    cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}",
                    legacy_cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}",
                ]
                for date_dir in date_dirs:
                    if not date_dir.exists():
                        continue
                    cache_candidates = []
                    for fp in date_dir.glob("*.parquet"):
                        if fp.stem.isdigit():
                            cache_candidates.append((int(fp.stem), fp))

                    if not cache_candidates:
                        continue
                    max_cached_count, best_cache_fp = max(cache_candidates, key=lambda x: x[0])
                    if max_cached_count >= count:
                        try:
                            cached_frames.append(pd.read_parquet(best_cache_fp, engine="pyarrow"))
                            found_cache = True
                            break
                        except Exception:
                            best_cache_fp.unlink(missing_ok=True)

            if not found_cache:
                missing_dates.append(exec_date)

        if not missing_dates:
            if cached_frames:
                final_df = pd.concat(cached_frames, ignore_index=True)
                final_df = final_df[(final_df["execution_timestamp"] >= start.astimezone(pytz.utc)) & (final_df["execution_timestamp"] <= end.astimezone(pytz.utc))]
                if merge_package_legs:
                    final_df = merge_package_legs_to_one_row(final_df)
                final_df["risk"] = final_df["estimated_pv01"].apply(_risk_from_estimated_pv01)
                final_df["risk"] = (final_df["risk"] / 100).round().mul(100)
                return final_df

            return pd.DataFrame()

        built_frames = []
        for exec_date in missing_dates:
            try:
                # ignore dates falling outside of execution
                # consequence: will drop modifications
                if exec_date > end.date() or exec_date < start.date():
                    continue

                day_df = raw_sdr_trades_df[raw_sdr_trades_df["_execution_date"] == exec_date]

                if use_v2_classification:
                    classifications = _classify_messages_v2(
                        day_df, exec_date=exec_date, curve_source=curve_source, **kwargs,
                    )
                else:
                    classifications = self.classify_messages(
                        day_df,
                        curve=mdp.get_pricer(dict(curve_name="USD-SOFR-1D", timestamp=exec_date)),
                    )
                classifications_df = classifications_to_dataframe(classifications)
                if not classifications_df.empty:
                    classifications_df[TRADE_ID] = classifications_df[TRADE_ID].astype("string")
                    day_df = day_df.copy()
                    day_df[TRADE_ID] = day_df[TRADE_ID].astype("string")

                # --- Lifecycle V2 resolution ---
                # Pass full day's raw data (all action types) through lifecycle resolver.
                # Only NEWT-bearing UTI groups produce output; result is indexed by
                # NEWT dissemination ID for merge onto classified rows.
                from SDRUtils.core.lifecycle import resolve_lifecycle_for_day

                lifecycle_df = resolve_lifecycle_for_day(day_df)
                if not lifecycle_df.empty and not classifications_df.empty:
                    lifecycle_df.index = lifecycle_df.index.astype("string")
                    classifications_df = classifications_df.merge(
                        lifecycle_df,
                        left_on=TRADE_ID,
                        right_index=True,
                        how="left",
                    )

                package_df = classifications_df.merge(
                    day_df[
                        # this is temp
                        [
                            TRADE_ID,
                            "UPI Underlier Name",
                            "Unique Product Identifier",
                            "Platform identifier",
                            "Cleared",
                            "Prime brokerage transaction indicator",
                            "Block trade election indicator",
                            "Large notional off-facility swap election indicator",
                            "Other payment type",  # non-par
                            "Other payment amount",
                            "Package indicator",
                            "Package transaction spread",
                        ]
                    ],
                    on=TRADE_ID,
                    how="left",
                )

                package_df = package_df.drop(columns=[TRADE_ID])
                package_df.columns = [re.sub(r"(?<!^)(?=[A-Z])", "_", col.lower()).lower().replace(" ", "_") for col in package_df.columns]

                if detect_fly:
                    package_df = detect_fly_trades_df(package_df)
                if detect_curve:
                    package_df = detect_curve_trades_df(package_df)
                if detect_mms:
                    package_df = detect_mms_trades_df(package_df)
                if detect_invoice:
                    package_df = detect_invoice_swaps(package_df)
                if detect_mac:
                    package_df = detect_mac_swaps(package_df)
                if detect_spreadover:
                    package_df = detect_spreadovers(package_df)

                # Final rollup: resolve unified special_tenor fields from all detectors
                package_df = _resolve_special_tenor_priority(package_df)

                # Normalize mixed object/string numerics before parquet serialization.
                package_df = _prepare_cache_dataframe_for_arrow(package_df)

                count = len(day_df)
                date_dir = cache_base / f"{exec_date.year:04d}" / f"{exec_date.month:02d}" / f"{exec_date}"
                date_dir.mkdir(parents=True, exist_ok=True)
                cache_fp = date_dir / f"{count}.parquet"
                tmp_fp = cache_fp.with_suffix(".parquet.tmp")
                table = pa.Table.from_pandas(package_df, preserve_index=False)
                pq.write_table(table, tmp_fp, compression="zstd")
                tmp_fp.replace(cache_fp)

                built_frames.append(package_df)
            
            # todo handle errors
            except Exception as e: 
                pass

        all_frames = [*cached_frames, *built_frames]
        if not all_frames:
            return pd.DataFrame()

        final_df = pd.concat(all_frames, ignore_index=True)
        final_df = final_df[(final_df["execution_timestamp"] >= start.astimezone(pytz.utc)) & (final_df["execution_timestamp"] <= end.astimezone(pytz.utc))]
        if merge_package_legs:
            final_df = merge_package_legs_to_one_row(final_df)
        final_df["risk"] = final_df["estimated_pv01"].apply(_risk_from_estimated_pv01)
        final_df["risk"] = (final_df["risk"] / 100).round().mul(100)
        return final_df


__all__ = [
    "USD_SwapProduct",
    "classify_usd_swap_trade",
    "usd_swap_trades",
    "new_usd_swap_trades",
    "is_usd_swap",
    "detect_invoice_swaps",
    "detect_mac_swaps",
    "detect_spreadovers",
    "_is_round_notional",
    "_resolve_special_tenor_priority",
]
