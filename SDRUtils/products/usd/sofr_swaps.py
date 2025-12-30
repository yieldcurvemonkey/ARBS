"""
USD SOFR OIS Swap product module.

Provides classification and analysis for USD SOFR-based OIS swaps
reported to the DTCC SDR.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

import pandas as pd
import QuantLib as ql
from tqdm import tqdm

try:
    import Query.IRSwaps.adapter  # noqa: F401
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery

    HAS_CURVE_DEPS = True
except ImportError:
    HAS_CURVE_DEPS = False
    _IRSwapGenericCurve = None


from SDRUtils.config import PRODUCT_TYPES, TRADE_ID, USD_CONVENTIONS
from SDRUtils.core.classification import TradeClassification, classifications_to_dataframe, classify_product_type
from SDRUtils.core.dates import calculate_forward_start_years, calculate_tenor_years, to_ql_date
from SDRUtils.core.parsing import parse_notional
from SDRUtils.core.tenors import build_trade_label, forward_to_label, tenor_to_label
from SDRUtils.data.builder import SDRDataBuilder
from SDRUtils.packages import detect_curve_trades_df, detect_fly_trades_df, detect_mms_trades_df, merge_package_legs_to_one_row
from SDRUtils.products.usd.base import USDProductBase
from SDRUtils.products.usd.filters import new_sofr_swap_trades


def classify_sofr_swap_trade(
    row: pd.Series,
    trade_id: int,
    curve: Optional[Any] = None,
    *,
    calculate_pv01: bool = True,
) -> TradeClassification:
    """
    Classify a single USD SOFR OIS swap from SDR data.

    This function extracts all relevant trade characteristics:
    - Product type (OIS_SWAP, SWAPTION, etc.)
    - Tenor and forward start calculations
    - Special date detection (IMM/FOMC)
    - PV01 calculation (if curve provided)

    Args:
        row: SDR data row as pandas Series
        trade_id: Unique identifier for the trade
        curve: Optional curve object for PV01 calculation
        calculate_pv01: Whether to calculate PV01 (requires curve)

    Returns:
        TradeClassification object with all trade details
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
    tenor_label = tenor_to_label(tenor_years, expiration_date=expiration_date)

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

    # Extract notional and rate
    notional = parse_notional(row.get("Notional amount-Leg 1", 0))
    fixed_rate = row.get("Fixed rate-Leg 1")
    strike = row.get("Strike Price")

    # Calculate PV01 if curve provided
    pv01 = 0.0
    if calculate_pv01 and curve is not None and HAS_CURVE_DEPS:
        try:
            pkg, _ = IRSwapQuery(
                curve="USD-SOFR-1D", effective_date=effective_date.date(), maturity_date=expiration_date.date(), structure_kwargs={"notional": notional}
            ).resolve_package(pricer_or_curve=curve)
            pv01 = curve.pv01(pkg[0])
        except Exception:
            pv01 = 0.0

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


class USD_SOFR_SwapProduct(USDProductBase):
    """
    USD SOFR OIS Swap product implementation.

    This class implements the ProductModule interface for USD SOFR swaps,
    providing trade classification and product type inference.
    """

    name = "USD-SOFR-OIS"
    product_type = PRODUCT_TYPES.OIS_SWAP

    def classify_trade(self, row: pd.Series, trade_id: int, **kwargs: Any) -> TradeClassification:
        """
        Classify a single USD SOFR swap trade.

        Args:
            row: SDR data row
            trade_id: Trade identifier
            **kwargs: Additional arguments, including 'curve' for PV01

        Returns:
            TradeClassification object
        """
        curve = kwargs.get("curve")
        calculate_pv01 = kwargs.get("calculate_pv01", True)
        return classify_sofr_swap_trade(
            row,
            trade_id,
            curve,
            calculate_pv01=calculate_pv01,
        )

    def classify_product_type(self, row: pd.Series) -> str:
        """Infer product type from SDR row."""
        return classify_product_type(row)

    def build_classification_dataframe(
        self, start: datetime.datetime, end: datetime.datetime, cache_path: str, detect_curve=True, detect_fly=True, detect_mms=True, **kwargs: Any
    ):
        sdr = SDRDataBuilder(cache_path=cache_path, show_tqdm=True)
        raw_sdr_trades_df = sdr.grab_sdr_trades(
            start_timestamp=start,
            end_timestamp=end,
            agency="CFTC",
            asset_class="RATES",
            filter_func=new_sofr_swap_trades,
        )

        as_of_date = pd.to_datetime(raw_sdr_trades_df["Execution Timestamp"]).dt.date.value_counts().index[0]
        curve = IRSwapsMDP(kwargs.get("curve_source", "ERIS_EOD_LIVE-RL_BASIC")).get_pricer(request=dict(curve_name="USD-SOFR-1D", timestamp=as_of_date))

        classifications = [
            self.classify_trade(row, trade_id=row.get(TRADE_ID), kwargs={"curve": curve})
            for _, row in tqdm(raw_sdr_trades_df.iterrows(), total=raw_sdr_trades_df.shape[0], desc="Classifying Trades")
        ]
        classifications_df = classifications_to_dataframe(classifications)

        package_df = classifications_df.merge(
            raw_sdr_trades_df[
                [
                    TRADE_ID,
                    "UPI Underlier Name",
                    "Platform identifier",
                    "Cleared",
                ]
            ],
            on=TRADE_ID,
            how="left",
        )
        package_df = package_df.drop(columns=[TRADE_ID])

        if detect_fly:
            package_df = detect_fly_trades_df(package_df)
        if detect_curve:
            package_df = detect_curve_trades_df(package_df)
        if detect_mms:
            package_df = detect_mms_trades_df(package_df)

        return merge_package_legs_to_one_row(package_df)
