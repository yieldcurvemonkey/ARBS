"""
SOFR SDR Seasonality Analysis
=============================
Analyzes USD SOFR OIS Swaps and Swaptions from SDR data to identify:
- Month-end flows
- Quarter-end flows
- FOMC-related flows
- Package structures (curves, flies, straddles)

This module provides comprehensive trade classification and seasonality analysis.
"""

import datetime
import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple, Union

import numpy as np
import pandas as pd
import QuantLib as ql
import pytz

NY_tz = pytz.timezone("America/New_York")
UTC_tz = pytz.timezone("UTC")

# SOFR-related UPIs from definitions
SOFR_OIS_UPIS = ["QZXQ4R16245X", "QZPB5VSBGRCD"]

# UPI patterns for SOFR products
SOFR_UPI_PATTERNS = [
    "USD-SOFR",
    "SOFR",
]

# Swaption UPI patterns
SWAPTION_FISN_PATTERNS = [
    "O Call",  # Call swaption
    "O Put",   # Put swaption
    "Cap",     # Cap
    "Floor",   # Floor
    "Straddle",
    "Strangle",
]


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


def classify_product_type(row: pd.Series) -> Literal["OIS_SWAP", "SWAPTION_CALL", "SWAPTION_PUT", "CAP", "FLOOR", "UNKNOWN"]:
    """Classify the product type from SDR row"""
    upi_fisn = str(row.get("UPI FISN", "")).upper()
    upi_underlier = str(row.get("UPI Underlier Name", "")).upper()
    strike = row.get("Strike Price")
    option_premium = row.get("Option Premium Amount")
    first_exercise = row.get("First exercise date")

    # Check for swaptions/options
    if "O CALL" in upi_fisn or "CALL" in upi_fisn:
        return "SWAPTION_CALL"
    if "O PUT" in upi_fisn or "PUT" in upi_fisn:
        return "SWAPTION_PUT"
    if "CAP" in upi_fisn:
        return "CAP"
    if "FLOOR" in upi_fisn:
        return "FLOOR"

    # Check for strike/premium to identify options
    if pd.notna(strike) and strike > 0:
        if pd.notna(first_exercise):
            # Has strike and exercise date - likely swaption
            return "SWAPTION_CALL"  # Default to call if unclear

    # Check for OIS swap
    if "SWAP" in upi_fisn and "OIS" in upi_fisn:
        return "OIS_SWAP"
    if "SOFR" in upi_underlier and ("COMPOUND" in upi_underlier or "OIS" in upi_underlier):
        return "OIS_SWAP"

    # Check fixed rate for vanilla swap
    fixed_rate = row.get("Fixed rate-Leg 1")
    if pd.notna(fixed_rate) and fixed_rate > 0:
        return "OIS_SWAP"

    return "UNKNOWN"


def calculate_tenor_years(effective_date: pd.Timestamp, expiration_date: pd.Timestamp) -> float:
    """Calculate tenor in years from effective to expiration"""
    if pd.isna(effective_date) or pd.isna(expiration_date):
        return 0.0

    # Handle timezone-aware dates
    if hasattr(effective_date, 'tz') and effective_date.tz is not None:
        effective_date = effective_date.tz_localize(None)
    if hasattr(expiration_date, 'tz') and expiration_date.tz is not None:
        expiration_date = expiration_date.tz_localize(None)

    days = (expiration_date - effective_date).days
    return days / 365.25


def calculate_forward_start_years(execution_timestamp: pd.Timestamp, effective_date: pd.Timestamp) -> float:
    """Calculate forward start in years from execution to effective"""
    if pd.isna(execution_timestamp) or pd.isna(effective_date):
        return 0.0

    # Normalize to date only
    exec_date = execution_timestamp.date() if hasattr(execution_timestamp, 'date') else execution_timestamp
    eff_date = effective_date.date() if hasattr(effective_date, 'date') else effective_date

    if isinstance(exec_date, pd.Timestamp):
        exec_date = exec_date.date()
    if isinstance(eff_date, pd.Timestamp):
        eff_date = eff_date.date()

    days = (eff_date - exec_date).days
    return max(0, days / 365.25)


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


def filter_sofr_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Filter DataFrame to only SOFR-related trades"""
    if df.empty:
        return df

    # Filter by UPI underlier name containing SOFR
    mask = pd.Series([False] * len(df))

    upi_underlier = df["UPI Underlier Name"].fillna("").str.upper()
    upi_fisn = df["UPI FISN"].fillna("").str.upper()

    # SOFR OIS swaps
    mask |= upi_underlier.str.contains("SOFR", na=False)

    # Also check for known UPIs
    if "Unique Product Identifier" in df.columns:
        upi = df["Unique Product Identifier"].fillna("")
        mask |= upi.isin(SOFR_OIS_UPIS)

    return df[mask].copy()


def filter_new_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to only new trades (not amendments/corrections)"""
    if df.empty:
        return df

    # Only NEWT action type
    if "Action type" in df.columns:
        mask = df["Action type"] == "NEWT"
        return df[mask].copy()
    return df


def detect_curve_trades(
    classifications: List[TradeClassification],
    time_window_seconds: int = 60,
    pv01_tolerance: float = 0.10,  # 10% tolerance
) -> List[TradeClassification]:
    """
    Detect curve trades: two legs with matching PV01 within time window

    Curve trade = pay one tenor, receive another (equal and opposite PV01)
    """
    if len(classifications) < 2:
        return classifications

    # Sort by execution time
    sorted_trades = sorted(classifications, key=lambda x: x.execution_timestamp)

    matched_indices = set()
    package_counter = 0

    for i, trade1 in enumerate(sorted_trades):
        if i in matched_indices:
            continue
        if trade1.product_type != "OIS_SWAP":
            continue
        if trade1.estimated_pv01 <= 0:
            continue

        for j, trade2 in enumerate(sorted_trades[i+1:], start=i+1):
            if j in matched_indices:
                continue
            if trade2.product_type != "OIS_SWAP":
                continue
            if trade2.estimated_pv01 <= 0:
                continue

            # Check time window
            time_diff = abs((trade2.execution_timestamp - trade1.execution_timestamp).total_seconds())
            if time_diff > time_window_seconds:
                break  # Sorted by time, no more matches possible

            # Check PV01 match (within tolerance)
            pv01_diff = abs(trade1.estimated_pv01 - trade2.estimated_pv01)
            avg_pv01 = (trade1.estimated_pv01 + trade2.estimated_pv01) / 2

            if pv01_diff / avg_pv01 <= pv01_tolerance:
                # Different tenors?
                if trade1.tenor_label != trade2.tenor_label:
                    # This is a curve trade!
                    package_counter += 1
                    pkg_id = f"CURVE_{package_counter}"

                    trade1.package_type = "CURVE"
                    trade1.package_id = pkg_id
                    trade1.package_legs = [trade1.trade_id, trade2.trade_id]

                    trade2.package_type = "CURVE"
                    trade2.package_id = pkg_id
                    trade2.package_legs = [trade1.trade_id, trade2.trade_id]

                    matched_indices.add(i)
                    matched_indices.add(j)
                    break

    return sorted_trades


def detect_fly_trades(
    classifications: List[TradeClassification],
    time_window_seconds: int = 60,
    belly_ratio_tolerance: float = 0.15,  # 15% tolerance for 2:1 ratio
) -> List[TradeClassification]:
    """
    Detect butterfly trades: three legs where belly has ~2x PV01 of wings

    Fly = pay wings, receive belly (or vice versa)
    Belly PV01 ≈ 2 × Wing PV01
    """
    if len(classifications) < 3:
        return classifications

    # Get OIS swaps not already in packages
    available = [t for t in classifications if t.product_type == "OIS_SWAP"
                 and t.package_type == "OUTRIGHT" and t.estimated_pv01 > 0]

    if len(available) < 3:
        return classifications

    # Sort by execution time
    sorted_trades = sorted(available, key=lambda x: x.execution_timestamp)

    matched_indices = set()
    package_counter = 0

    for i in range(len(sorted_trades)):
        if i in matched_indices:
            continue
        trade1 = sorted_trades[i]

        for j in range(i+1, len(sorted_trades)):
            if j in matched_indices:
                continue
            trade2 = sorted_trades[j]

            # Check time window for first two
            time_diff_12 = abs((trade2.execution_timestamp - trade1.execution_timestamp).total_seconds())
            if time_diff_12 > time_window_seconds:
                break

            for k in range(j+1, len(sorted_trades)):
                if k in matched_indices:
                    continue
                trade3 = sorted_trades[k]

                # Check time window for third
                time_diff_13 = abs((trade3.execution_timestamp - trade1.execution_timestamp).total_seconds())
                if time_diff_13 > time_window_seconds:
                    break

                # Sort by tenor to find wings vs belly
                trio = sorted([trade1, trade2, trade3], key=lambda x: x.tenor_years)
                wing1, belly, wing2 = trio

                # Check if belly has ~2x PV01 of each wing
                if wing1.estimated_pv01 > 0 and wing2.estimated_pv01 > 0:
                    # Wings should have similar PV01
                    wing_avg = (wing1.estimated_pv01 + wing2.estimated_pv01) / 2
                    wing_diff = abs(wing1.estimated_pv01 - wing2.estimated_pv01) / wing_avg

                    if wing_diff < belly_ratio_tolerance:
                        # Belly should be ~2x wing
                        expected_belly = wing_avg * 2
                        belly_diff = abs(belly.estimated_pv01 - expected_belly) / expected_belly

                        if belly_diff < belly_ratio_tolerance:
                            # This is a fly!
                            package_counter += 1
                            pkg_id = f"FLY_{package_counter}"

                            for t in [wing1, belly, wing2]:
                                t.package_type = "FLY"
                                t.package_id = pkg_id
                                t.package_legs = [wing1.trade_id, belly.trade_id, wing2.trade_id]

                            matched_indices.add(sorted_trades.index(trade1))
                            matched_indices.add(sorted_trades.index(trade2))
                            matched_indices.add(sorted_trades.index(trade3))

    return classifications


def detect_straddles_strangles(
    classifications: List[TradeClassification],
    time_window_seconds: int = 60,
    notional_tolerance: float = 0.05,  # 5% tolerance
) -> List[TradeClassification]:
    """
    Detect straddles (same strike) and strangles (different strikes)

    Straddle = call + put with same strike, expiry, underlying tenor
    Strangle = call + put with different strikes, same expiry, underlying tenor
    """
    # Get swaptions not in packages
    swaptions = [t for t in classifications
                 if t.product_type in ["SWAPTION_CALL", "SWAPTION_PUT"]
                 and t.package_type == "OUTRIGHT"]

    if len(swaptions) < 2:
        return classifications

    sorted_trades = sorted(swaptions, key=lambda x: x.execution_timestamp)

    matched_indices = set()
    package_counter = 0

    for i, trade1 in enumerate(sorted_trades):
        if i in matched_indices:
            continue

        for j, trade2 in enumerate(sorted_trades[i+1:], start=i+1):
            if j in matched_indices:
                continue

            # Must be call/put pair
            if trade1.product_type == trade2.product_type:
                continue

            # Check time window
            time_diff = abs((trade2.execution_timestamp - trade1.execution_timestamp).total_seconds())
            if time_diff > time_window_seconds:
                break

            # Check same underlying tenor
            if trade1.tenor_label != trade2.tenor_label:
                continue

            # Check same forward start
            if trade1.forward_label != trade2.forward_label:
                continue

            # Check similar notional
            if trade1.notional > 0 and trade2.notional > 0:
                notional_diff = abs(trade1.notional - trade2.notional) / max(trade1.notional, trade2.notional)
                if notional_diff > notional_tolerance:
                    continue

            # Determine straddle vs strangle
            package_counter += 1
            if trade1.strike == trade2.strike:
                pkg_type = "STRADDLE"
            else:
                pkg_type = "STRANGLE"

            pkg_id = f"{pkg_type}_{package_counter}"

            trade1.package_type = pkg_type
            trade1.package_id = pkg_id
            trade1.package_legs = [trade1.trade_id, trade2.trade_id]

            trade2.package_type = pkg_type
            trade2.package_id = pkg_id
            trade2.package_legs = [trade1.trade_id, trade2.trade_id]

            matched_indices.add(i)
            matched_indices.add(j)
            break

    return classifications


def classify_all_trades(df: pd.DataFrame) -> List[TradeClassification]:
    """Classify all trades in DataFrame and detect packages"""
    classifications = []

    for idx, row in df.iterrows():
        trade_id = int(row.get("Dissemination Identifier", idx))
        try:
            classification = classify_trade(row, trade_id)
            classifications.append(classification)
        except Exception as e:
            print(f"Error classifying trade {trade_id}: {e}")
            continue

    # Detect packages
    classifications = detect_curve_trades(classifications)
    classifications = detect_fly_trades(classifications)
    classifications = detect_straddles_strangles(classifications)

    return classifications


def classifications_to_dataframe(classifications: List[TradeClassification]) -> pd.DataFrame:
    """Convert list of classifications to DataFrame"""
    records = []
    for c in classifications:
        records.append({
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
        })

    return pd.DataFrame(records)


# ============================================================================
# Seasonality Analysis Functions
# ============================================================================

def get_fomc_dates() -> List[datetime.date]:
    """Get list of FOMC meeting dates"""
    from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
    dates = [m[0] for m in _CENTRAL_BANK_DATES["USD-SOFR-1D"].values()]
    return sorted(dates)


def get_month_end_dates(start: datetime.date, end: datetime.date) -> List[datetime.date]:
    """Get business month end dates"""
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    dates = []

    current = datetime.date(start.year, start.month, 1)
    while current <= end:
        ql_date = ql.Date(1, current.month, current.year)
        month_end = cal.endOfMonth(ql_date)
        py_date = datetime.date(month_end.year(), month_end.month(), month_end.dayOfMonth())
        if start <= py_date <= end:
            dates.append(py_date)

        # Next month
        if current.month == 12:
            current = datetime.date(current.year + 1, 1, 1)
        else:
            current = datetime.date(current.year, current.month + 1, 1)

    return dates


def get_quarter_end_dates(start: datetime.date, end: datetime.date) -> List[datetime.date]:
    """Get business quarter end dates"""
    all_month_ends = get_month_end_dates(start, end)
    return [d for d in all_month_ends if d.month in [3, 6, 9, 12]]


def classify_date(
    trade_date: datetime.date,
    fomc_dates: List[datetime.date],
    month_end_dates: List[datetime.date],
    quarter_end_dates: List[datetime.date],
    days_before: int = 3,
) -> Dict[str, bool]:
    """
    Classify a trade date relative to events

    Returns dict with flags for each event type
    """
    result = {
        "is_month_end_window": False,
        "is_quarter_end_window": False,
        "is_fomc_window": False,
        "is_fomc_day": False,
        "days_to_month_end": None,
        "days_to_quarter_end": None,
        "days_to_fomc": None,
    }

    # Month end
    for me in month_end_dates:
        delta = (me - trade_date).days
        if 0 <= delta <= days_before:
            result["is_month_end_window"] = True
            result["days_to_month_end"] = delta
            break

    # Quarter end
    for qe in quarter_end_dates:
        delta = (qe - trade_date).days
        if 0 <= delta <= days_before:
            result["is_quarter_end_window"] = True
            result["days_to_quarter_end"] = delta
            break

    # FOMC
    for fomc in fomc_dates:
        delta = (fomc - trade_date).days
        if delta == 0:
            result["is_fomc_day"] = True
            result["is_fomc_window"] = True
            result["days_to_fomc"] = 0
            break
        elif 0 < delta <= days_before:
            result["is_fomc_window"] = True
            result["days_to_fomc"] = delta
            break

    return result


def add_event_classifications(
    df: pd.DataFrame,
    date_col: str = "execution_timestamp",
) -> pd.DataFrame:
    """Add event classification columns to DataFrame"""
    df = df.copy()

    # Get date range
    dates = pd.to_datetime(df[date_col])
    min_date = dates.min().date()
    max_date = dates.max().date()

    # Get event dates
    fomc_dates = get_fomc_dates()
    month_end_dates = get_month_end_dates(min_date, max_date)
    quarter_end_dates = get_quarter_end_dates(min_date, max_date)

    # Classify each trade
    classifications = []
    for ts in dates:
        trade_date = ts.date() if hasattr(ts, 'date') else ts
        cls = classify_date(trade_date, fomc_dates, month_end_dates, quarter_end_dates)
        classifications.append(cls)

    cls_df = pd.DataFrame(classifications)
    for col in cls_df.columns:
        df[col] = cls_df[col].values

    return df


def aggregate_flows_by_label(
    df: pd.DataFrame,
    value_col: str = "notional",
    agg_func: str = "sum",
) -> pd.DataFrame:
    """
    Aggregate flows by trade label (e.g., "spot 10Y", "5Y10Y")

    Returns DataFrame with trade labels as index and aggregated values
    """
    grouped = df.groupby("trade_label")[value_col].agg(agg_func)
    return grouped.sort_values(ascending=False)


def analyze_seasonality_by_event(
    df: pd.DataFrame,
    event_col: str,
    value_col: str = "notional",
) -> pd.DataFrame:
    """
    Analyze how flows differ during events vs non-events

    Returns comparison DataFrame
    """
    event_trades = df[df[event_col] == True]
    non_event_trades = df[df[event_col] == False]

    results = []

    for label in df["trade_label"].unique():
        event_vol = event_trades[event_trades["trade_label"] == label][value_col].sum()
        non_event_vol = non_event_trades[non_event_trades["trade_label"] == label][value_col].sum()

        event_count = len(event_trades[event_trades["trade_label"] == label])
        non_event_count = len(non_event_trades[non_event_trades["trade_label"] == label])

        total_event_days = df[df[event_col] == True]["execution_timestamp"].dt.date.nunique()
        total_non_event_days = df[df[event_col] == False]["execution_timestamp"].dt.date.nunique()

        results.append({
            "trade_label": label,
            "event_volume": event_vol,
            "non_event_volume": non_event_vol,
            "event_trade_count": event_count,
            "non_event_trade_count": non_event_count,
            "event_avg_daily": event_vol / max(1, total_event_days),
            "non_event_avg_daily": non_event_vol / max(1, total_non_event_days),
            "volume_ratio": event_vol / max(1, non_event_vol),
        })

    result_df = pd.DataFrame(results)
    return result_df.sort_values("volume_ratio", ascending=False)


def generate_seasonality_report(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Generate comprehensive seasonality report

    Returns dict of analysis DataFrames
    """
    report = {}

    # Overall volume by trade label
    report["overall_volume_by_label"] = aggregate_flows_by_label(df, "notional", "sum")
    report["overall_count_by_label"] = aggregate_flows_by_label(df, "notional", "count")

    # Volume by product type
    report["volume_by_product"] = df.groupby("product_type")["notional"].agg(["sum", "count", "mean"])

    # Volume by package type
    report["volume_by_package"] = df.groupby("package_type")["notional"].agg(["sum", "count", "mean"])

    # Month-end analysis
    report["month_end_analysis"] = analyze_seasonality_by_event(df, "is_month_end_window")

    # Quarter-end analysis
    report["quarter_end_analysis"] = analyze_seasonality_by_event(df, "is_quarter_end_window")

    # FOMC analysis
    report["fomc_analysis"] = analyze_seasonality_by_event(df, "is_fomc_window")

    # Top trades on FOMC days
    fomc_trades = df[df["is_fomc_day"] == True]
    if not fomc_trades.empty:
        report["fomc_day_top_trades"] = aggregate_flows_by_label(fomc_trades, "notional", "sum").head(20)

    # Curve trades breakdown
    curve_trades = df[df["package_type"] == "CURVE"]
    if not curve_trades.empty:
        report["curve_trades_by_label"] = curve_trades.groupby("trade_label")["notional"].agg(["sum", "count"])

    # Fly trades breakdown
    fly_trades = df[df["package_type"] == "FLY"]
    if not fly_trades.empty:
        report["fly_trades_by_label"] = fly_trades.groupby("trade_label")["notional"].agg(["sum", "count"])

    return report


# ============================================================================
# Main Analysis Pipeline
# ============================================================================

def run_sofr_seasonality_analysis(
    sdr_df: pd.DataFrame,
    verbose: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    """
    Run complete SOFR seasonality analysis

    Args:
        sdr_df: Raw SDR data DataFrame
        verbose: Print progress

    Returns:
        Tuple of (classified trades DataFrame, seasonality report dict)
    """
    if verbose:
        print(f"Starting analysis with {len(sdr_df)} raw trades...")

    # Filter to SOFR trades
    sofr_df = filter_sofr_trades(sdr_df)
    if verbose:
        print(f"Filtered to {len(sofr_df)} SOFR trades")

    # Filter to new trades only
    new_df = filter_new_trades(sofr_df)
    if verbose:
        print(f"Filtered to {len(new_df)} new trades (NEWT)")

    if new_df.empty:
        print("No trades to analyze!")
        return pd.DataFrame(), {}

    # Classify trades
    if verbose:
        print("Classifying trades...")
    classifications = classify_all_trades(new_df)
    trades_df = classifications_to_dataframe(classifications)

    if verbose:
        print(f"Classified {len(trades_df)} trades")
        print(f"  - OIS Swaps: {len(trades_df[trades_df['product_type'] == 'OIS_SWAP'])}")
        print(f"  - Swaptions: {len(trades_df[trades_df['product_type'].str.contains('SWAPTION')])}")
        print(f"  - Curve trades: {len(trades_df[trades_df['package_type'] == 'CURVE'])}")
        print(f"  - Fly trades: {len(trades_df[trades_df['package_type'] == 'FLY'])}")
        print(f"  - Straddles: {len(trades_df[trades_df['package_type'] == 'STRADDLE'])}")

    # Add event classifications
    if verbose:
        print("Adding event classifications...")
    trades_df = add_event_classifications(trades_df)

    # Generate report
    if verbose:
        print("Generating seasonality report...")
    report = generate_seasonality_report(trades_df)

    return trades_df, report


if __name__ == "__main__":
    # Example usage
    print("SOFR SDR Seasonality Analysis Module")
    print("=====================================")
    print("Import and use run_sofr_seasonality_analysis(sdr_df) to analyze SDR data")
