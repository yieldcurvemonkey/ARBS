"""
USD SOFR OIS Swap product module.

Provides classification and analysis for USD SOFR-based OIS swaps
reported to the DTCC SDR.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd
import QuantLib as ql

# Import curve dependencies (optional - for PV01 calculation)
try:
    import Query.IRSwaps.adapter  # noqa: F401
    from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    HAS_CURVE_DEPS = True
except ImportError:
    HAS_CURVE_DEPS = False
    _IRSwapGenericCurve = None

from SDRUtils.config import USD_CONVENTIONS, PRODUCT_TYPES
from SDRUtils.core.classification import TradeClassification, classify_product_type
from SDRUtils.core.dates import (
    to_ql_date,
    calculate_tenor_years,
    calculate_forward_start_years,
)
from SDRUtils.core.tenors import tenor_to_label, forward_to_label, build_trade_label
from SDRUtils.core.parsing import parse_notional
from SDRUtils.products.usd.base import USDProductBase


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
        effective_date, expiration_date,
        conventions=USD_CONVENTIONS,
    )
    tenor_label = tenor_to_label(tenor_years, expiration_date=expiration_date)

    # Calculate forward start
    forward_years = calculate_forward_start_years(
        execution_ts, effective_date,
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
                curve="USD-SOFR-1D",
                effective_date=effective_date.date(),
                maturity_date=expiration_date.date(),
                structure_kwargs={"notional": notional}
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

    def classify_trade(
        self, row: pd.Series, trade_id: int, **kwargs: Any
    ) -> TradeClassification:
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
            row, trade_id, curve,
            calculate_pv01=calculate_pv01,
        )

    def classify_product_type(self, row: pd.Series) -> str:
        """Infer product type from SDR row."""
        return classify_product_type(row)
