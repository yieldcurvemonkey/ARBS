from dataclasses import dataclass
from typing import List, Literal, Optional, Union

import numpy as np
import pandas as pd
import QuantLib as ql


@dataclass
class TradeClassification:
    """Classification of an SDR trade"""

    trade_id: int
    execution_timestamp: pd.Timestamp
    effective_date: pd.Timestamp
    expiration_date: pd.Timestamp

    # Product type
    product_type: Literal["OIS_SWAP", "SWAPTION_CALL", "SWAPTION_PUT", "CAP", "FLOOR", "UNKNOWN"]

    # Tenor information
    tenor_years: float
    tenor_label: str  # e.g., "2Y", "5Y", "10Y"

    # Forward start info (for forward swaps/swaptions)
    is_forward: bool
    forward_start_years: float
    forward_label: str  # e.g., "spot", "1Y", "5Y"

    # Full trade label e.g., "spot 10Y", "5Y10Y", "1Y1Y"
    trade_label: str

    # Notional and risk
    notional: float
    notional_currency: str
    fixed_rate: Optional[float]
    strike: Optional[float]

    # Estimated PV01 (per 1bp)
    estimated_pv01: float

    # Package info
    package_type: Optional[Literal["CURVE", "FLY", "STRADDLE", "STRANGLE", "OUTRIGHT"]] = None
    package_id: Optional[str] = None
    package_legs: Optional[List[int]] = None


def parse_notional(notional_str: Union[str, float, int]) -> float:
    """Parse notional string like '31,000,000' to float"""
    if pd.isna(notional_str) or notional_str == "":
        return 0.0
    if isinstance(notional_str, (int, float)):
        return float(notional_str)
    # Remove commas and convert
    try:
        return float(str(notional_str).replace(",", "").strip())
    except:
        return 0.0


def _to_float(x) -> float:
    if pd.isna(x) or x == "":
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return np.nan


def classify_product_type(row: pd.Series) -> Literal["OIS_SWAP", "SWAPTION_CALL", "SWAPTION_PUT", "CAP", "FLOOR", "UNKNOWN"]:
    upi_fisn = str(row.get("UPI FISN", "")).upper()
    upi_underlier = str(row.get("UPI Underlier Name", "")).upper()

    strike = _to_float(row.get("Strike Price"))
    fixed_rate = _to_float(row.get("Fixed rate-Leg 1"))

    first_exercise = row.get("First exercise date")
    # normalize if you want:
    first_exercise = pd.to_datetime(first_exercise, errors="coerce") if not isinstance(first_exercise, pd.Timestamp) else first_exercise

    # Explicit option labeling from FISN first
    if "O CALL" in upi_fisn or "CALL" in upi_fisn:
        return "SWAPTION_CALL"
    if "O PUT" in upi_fisn or "PUT" in upi_fisn:
        return "SWAPTION_PUT"
    if "CAP" in upi_fisn:
        return "CAP"
    if "FLOOR" in upi_fisn:
        return "FLOOR"

    # Strike-based option inference (now safe)
    if pd.notna(strike) and strike > 0:
        if pd.notna(first_exercise):
            return "SWAPTION_CALL"  # default if unclear

    # OIS swap inference
    if "SWAP" in upi_fisn and "OIS" in upi_fisn:
        return "OIS_SWAP"
    if "SOFR" in upi_underlier and ("COMPOUND" in upi_underlier or "OIS" in upi_underlier):
        return "OIS_SWAP"

    # Fixed rate inference (now safe)
    if pd.notna(fixed_rate) and fixed_rate > 0:
        return "OIS_SWAP"

    return "UNKNOWN"


_USD_OIS_CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
_USD_OIS_DC = ql.Actual360()
_USD_OIS_BDC = ql.ModifiedFollowing  # common; you can set Following if you prefer


def _to_naive_timestamp(x) -> pd.Timestamp:
    ts = pd.to_datetime(x, errors="coerce")
    if pd.isna(ts):
        return ts
    # drop tz to avoid ql.Date confusion
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert(None)
    return ts


def _ts_to_ql_date(ts: pd.Timestamp) -> ql.Date:
    return ql.Date(int(ts.day), int(ts.month), int(ts.year))


def calculate_tenor_years(
    effective_date: pd.Timestamp,
    expiration_date: pd.Timestamp,
    *,
    day_counter: ql.DayCounter = _USD_OIS_DC,
    calendar: ql.Calendar = _USD_OIS_CAL,
    bdc: int = _USD_OIS_BDC,
    adjust_to_business_day: bool = True,
) -> float:
    """
    Trading-standard year fraction for tenor between effective and expiration.

    Defaults: ACT/360 with USD GovBond calendar and Modified Following adjustment.
    """
    eff = _to_naive_timestamp(effective_date)
    exp = _to_naive_timestamp(expiration_date)
    if pd.isna(eff) or pd.isna(exp):
        return 0.0

    ql_eff = _ts_to_ql_date(eff)
    ql_exp = _ts_to_ql_date(exp)

    if adjust_to_business_day:
        if not calendar.isBusinessDay(ql_eff):
            ql_eff = calendar.adjust(ql_eff, bdc)
        if not calendar.isBusinessDay(ql_exp):
            ql_exp = calendar.adjust(ql_exp, bdc)

    # Defensive: negative/zero tenors -> 0
    if ql_exp <= ql_eff:
        return 0.0

    return float(day_counter.yearFraction(ql_eff, ql_exp))


def calculate_forward_start_years(
    execution_timestamp: pd.Timestamp,
    effective_date: pd.Timestamp,
    *,
    day_counter: ql.DayCounter = _USD_OIS_DC,
    calendar: ql.Calendar = _USD_OIS_CAL,
    bdc: int = _USD_OIS_BDC,
    adjust_to_business_day: bool = False,
    use_execution_date_only: bool = True,
) -> float:
    """
    Forward start year fraction from execution -> effective using trading-standard day count.

    Defaults:
      - ACT/360
      - execution_date_only=True: uses execution *date* (ignores time-of-day) for stability
      - adjust_to_business_day=False: leaves dates as-reported (toggle if you want calendar adjustment)
    """
    exec_ts = _to_naive_timestamp(execution_timestamp)
    eff_ts = _to_naive_timestamp(effective_date)
    if pd.isna(exec_ts) or pd.isna(eff_ts):
        return 0.0

    if use_execution_date_only:
        exec_ts = exec_ts.normalize()

    ql_exec = _ts_to_ql_date(exec_ts)
    ql_eff = _ts_to_ql_date(eff_ts)

    if adjust_to_business_day:
        if not calendar.isBusinessDay(ql_exec):
            ql_exec = calendar.adjust(ql_exec, bdc)
        if not calendar.isBusinessDay(ql_eff):
            ql_eff = calendar.adjust(ql_eff, bdc)

    if ql_eff <= ql_exec:
        return 0.0

    return float(day_counter.yearFraction(ql_exec, ql_eff))


def tenor_to_label(years: float) -> str:
    """Convert tenor in years to label like '2Y', '5Y', '10Y'"""
    if years <= 0:
        return "0D"

    # Common tenors
    tenor_map = {
        0.25: "3M",
        0.5: "6M",
        0.75: "9M",
        1.0: "1Y",
        1.5: "18M",
        2.0: "2Y",
        3.0: "3Y",
        4.0: "4Y",
        5.0: "5Y",
        6.0: "6Y",
        7.0: "7Y",
        8.0: "8Y",
        9.0: "9Y",
        10.0: "10Y",
        12.0: "12Y",
        15.0: "15Y",
        20.0: "20Y",
        25.0: "25Y",
        30.0: "30Y",
        40.0: "40Y",
        50.0: "50Y",
    }

    # Find closest match
    closest = min(tenor_map.keys(), key=lambda x: abs(x - years))
    if abs(closest - years) < 0.15:  # Within ~2 months
        return tenor_map[closest]

    # Otherwise, return rounded year
    if years < 1:
        months = int(round(years * 12))
        return f"{months}M"
    else:
        return f"{int(round(years))}Y"


def forward_to_label(years: float) -> str:
    """Convert forward start in years to label"""
    if years < 0.05:  # Less than ~2 weeks
        return "spot"
    return tenor_to_label(years)


def estimate_pv01(notional: float, tenor_years: float, product_type: str) -> float:
    """
    Estimate PV01 (per 1bp) for a swap

    Simple approximation: PV01 ≈ Notional × Tenor × 0.0001
    More accurate would use actual curve, but this is sufficient for matching
    """
    if notional <= 0 or tenor_years <= 0:
        return 0.0

    # For swaps: PV01 ≈ Notional × Modified Duration × 0.0001
    # Modified Duration ≈ Tenor for par swaps
    # So PV01 ≈ Notional × Tenor × 0.0001

    if product_type in ["OIS_SWAP"]:
        return notional * tenor_years * 0.0001
    elif product_type in ["SWAPTION_CALL", "SWAPTION_PUT"]:
        # Swaption delta depends on moneyness, assume ~50 delta for ATM
        return notional * tenor_years * 0.0001 * 0.5
    else:
        return notional * tenor_years * 0.0001


def classify_trade(row: pd.Series, trade_id: int) -> TradeClassification:
    """Classify a single SDR trade"""

    execution_ts = pd.to_datetime(row.get("Execution Timestamp"))
    effective_date = pd.to_datetime(row.get("Effective Date"))
    expiration_date = pd.to_datetime(row.get("Expiration Date"))

    product_type = classify_product_type(row)

    tenor_years = calculate_tenor_years(effective_date, expiration_date)
    tenor_label = tenor_to_label(tenor_years)

    forward_years = calculate_forward_start_years(execution_ts, effective_date)
    is_forward = forward_years > 0.05  # More than ~2 weeks
    forward_label = forward_to_label(forward_years)

    # Build trade label
    if is_forward:
        trade_label = f"{forward_label}{tenor_label}"  # e.g., "5Y10Y"
    else:
        trade_label = f"spot {tenor_label}"  # e.g., "spot 10Y"

    notional = parse_notional(row.get("Notional amount-Leg 1", 0))
    fixed_rate = row.get("Fixed rate-Leg 1")
    strike = row.get("Strike Price")

    pv01 = estimate_pv01(notional, tenor_years, product_type)

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


def classifications_to_dataframe(classifications: List[TradeClassification]) -> pd.DataFrame:
    """Convert list of classifications to DataFrame"""
    records = []
    for c in classifications:
        records.append(
            {
                "trade_id": c.trade_id,
                "execution_timestamp": c.execution_timestamp,
                "effective_date": c.effective_date,
                "expiration_date": c.expiration_date,
                "product_type": c.product_type,
                "tenor_years": c.tenor_years,
                "tenor_label": c.tenor_label,
                "is_forward": c.is_forward,
                "forward_start_years": c.forward_start_years,
                "forward_label": c.forward_label,
                "trade_label": c.trade_label,
                "notional": c.notional,
                "notional_currency": c.notional_currency,
                "fixed_rate": c.fixed_rate,
                "strike": c.strike,
                "estimated_pv01": c.estimated_pv01,
                "package_type": c.package_type,
                "package_id": c.package_id,
            }
        )

    return pd.DataFrame(records)
