"""
USD SOFR Swap Classification.

Provides comprehensive trade classification for USD SOFR swaps
using curve pricing for PV01 calculation.
"""

import pandas as pd
import QuantLib as ql

from SDRUtils.models.trade_classification import TradeClassification
from SDRUtils.products.registry import classify_product_type
from SDRUtils.core.utils import (
    calculate_tenor_years,
    calculate_forward_start_years,
    tenor_to_label,
    forward_to_label,
    parse_notional,
    to_ql_date,
    USD_OIS_CAL,
)


def classify_sofr_swap_trade(row: pd.Series, trade_id: int, curve) -> TradeClassification:
    """
    Classify a single USD SOFR swap trade.

    This function provides full classification including:
    - Product type detection
    - Tenor calculation
    - Forward start detection
    - PV01 calculation using the provided curve

    Args:
        row: A pandas Series representing a single SDR trade row
        trade_id: The trade identifier
        curve: An _IRSwapGenericCurve instance for PV01 calculation

    Returns:
        TradeClassification with all fields populated
    """
    # Import here to avoid circular dependency
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery

    execution_ts = pd.to_datetime(row.get("Execution Timestamp"))
    effective_date = pd.to_datetime(row.get("Effective Date"))
    expiration_date = pd.to_datetime(row.get("Expiration Date"))

    product_type = classify_product_type(row)

    # 1. Calculate Tenor
    tenor_years = calculate_tenor_years(effective_date, expiration_date)
    tenor_label = tenor_to_label(tenor_years, expiration_date=expiration_date)

    # 2. Calculate Forward/Spot status
    forward_years = calculate_forward_start_years(execution_ts, effective_date)

    ql_exec = to_ql_date(execution_ts)
    ql_eff = to_ql_date(effective_date)

    is_forward = False
    if ql_exec and ql_eff:
        t_plus_2 = USD_OIS_CAL.advance(ql_exec, 2, ql.Days)
        if ql_eff > t_plus_2:
            is_forward = True

    forward_label = forward_to_label(forward_years, effective_date=effective_date)

    # 3. Build Trade Label
    is_special_forward = forward_label.startswith("IMM_") or forward_label.startswith("FOMC_")

    if is_forward or is_special_forward:
        trade_label = f"{forward_label} {tenor_label}"
    else:
        trade_label = f"spot {tenor_label}"

    notional = parse_notional(row.get("Notional amount-Leg 1", 0))
    fixed_rate = row.get("Fixed rate-Leg 1")
    strike = row.get("Strike Price")

    # Calculate PV01 using curve
    pkg, _ = IRSwapQuery(
        curve="USD-SOFR-1D",
        effective_date=effective_date.date(),
        maturity_date=expiration_date.date(),
        structure_kwargs={"notional": notional},
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
