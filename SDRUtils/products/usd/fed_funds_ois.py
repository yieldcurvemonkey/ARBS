from __future__ import annotations

from typing import Optional

import pandas as pd

from SDRUtils.core.dates import calculate_tenor_years, to_naive_timestamp
from SDRUtils.core.tenors import tenor_to_label, forward_to_label, build_trade_label, classify_intrinsic_special_tenor
from SDRUtils.core.parsing import parse_notional, to_float
from SDRUtils.products.usd.linear_base import (
    LinearProductType,
    RateIndex,
    TenorSegment,
    USDLinearClassification,
)
from SDRUtils.products.usd.upi_classifier import classify_rate_index


def classify_fed_funds_ois_trade(
    row: pd.Series,
    trade_id: int,
    curve=None,
) -> USDLinearClassification:
    upi_class = classify_rate_index(
        row.get("UPI Underlier Name"),
        row.get("UPI FISN"),
    )

    exec_ts = to_naive_timestamp(row.get("Execution Timestamp"))
    eff_date = to_naive_timestamp(row.get("Effective Date"))
    exp_date = to_naive_timestamp(row.get("Expiration Date"))
    notional, is_capped = parse_notional(row.get("Notional amount-Leg 1"))
    # Some reporters put the fixed rate on Leg 2 (leg order is not
    # normalized in the raw feed) — fall back when Leg 1 is empty/NaN.
    fixed_rate = to_float(row.get("Fixed rate-Leg 1"))
    if fixed_rate is None or pd.isna(fixed_rate):
        fixed_rate = to_float(row.get("Fixed rate-Leg 2"))

    tenor_years = calculate_tenor_years(eff_date, exp_date)
    tenor_segment = TenorSegment.from_years(tenor_years)
    tenor_label = tenor_to_label(tenor_years)
    # T+2 can span up to 6 calendar days (Friday + holiday Monday)
    forward_years = calculate_tenor_years(exec_ts, eff_date) if eff_date > exec_ts + pd.Timedelta(days=6) else 0.0
    # effective_date enables IMM/FOMC forward labels ("IMM_U2030", not "4Y2M")
    forward_label = forward_to_label(forward_years, effective_date=eff_date)
    is_forward = forward_years > 0.1
    trade_label = build_trade_label(forward_label, tenor_label, is_forward)

    # Intrinsic special-tenor (IMM / FOMC) classification — maturity-aware (a
    # FOMC-to-FOMC fed funds swap is tagged FOMC). Mirrors V1 classify path.
    special_tenor_type, special_tenor_confidence, special_tenor_tags = classify_intrinsic_special_tenor(
        effective_date=eff_date,
        expiration_date=exp_date,
        tenor_label=tenor_label,
        forward_label=forward_label,
        is_forward=is_forward,
    )

    rate_index = upi_class.rate_index or RateIndex.FED_FUNDS

    return USDLinearClassification(
        event_action=row.get("Action type", "NEWT"),
        trade_id=trade_id,
        execution_timestamp=exec_ts,
        effective_date=eff_date,
        expiration_date=exp_date,
        product_type="OIS_SWAP",
        trade_label=trade_label,
        notional=notional or 0.0,
        notional_currency="USD",
        is_notional_capped=is_capped,
        tenor_years=tenor_years,
        tenor_label=tenor_label,
        forward_start_years=forward_years,
        forward_label=forward_label,
        is_forward=is_forward,
        fixed_rate=fixed_rate,
        rate_index=rate_index,
        linear_product_type=LinearProductType.OIS,
        tenor_segment=tenor_segment,
        special_tenor_type=special_tenor_type,
        special_tenor_confidence=special_tenor_confidence,
        special_tenor_tags=special_tenor_tags,
    )
