from __future__ import annotations

from typing import List, Literal, Tuple

import numpy as np
import pandas as pd


def _parse_delimited_field(value, dtype=float, delim: str = " / ") -> List:
    """Parse a delimited string field into a list of values."""
    if pd.isna(value):
        return []
    if isinstance(value, str):
        parts = value.split(delim)
        result = []
        for p in parts:
            p = p.strip().replace(",", "")
            if dtype == float:
                try:
                    result.append(float(p))
                except ValueError:
                    result.append(np.nan)
            else:
                result.append(p)
        return result
    return [value, value]


def _parse_risk_reversal_legs(
    row: pd.Series,
    delim: str = " / ",
) -> Tuple[List[float], List[float], List[float], List[str]]:
    """Parse a collapsed risk reversal row into individual leg components."""
    strikes = _parse_delimited_field(row.get("strike"), dtype=float, delim=delim)
    premiums = _parse_delimited_field(row.get("premium"), dtype=float, delim=delim)
    notionals = _parse_delimited_field(row.get("notional"), dtype=float, delim=delim)
    product_types = _parse_delimited_field(row.get("product_type"), dtype=str, delim=delim)

    return strikes, premiums, notionals, product_types


def _identify_risk_reversal_structure(
    strikes: List[float],
    premiums: List[float],
    notionals: List[float],
    product_types: List[str],
    strike_tolerance: float = 0.0001,
) -> Tuple[
    Tuple[float, float, float],  # atm_strike, atm_payer_premium, atm_receiver_premium
    Tuple[float, float, float],  # otm_payer_strike, otm_payer_premium, otm_payer_notional
    Tuple[float, float, float],  # otm_receiver_strike, otm_receiver_premium, otm_receiver_notional
    float,  # atm_notional
]:
    """
    Identify the structure of a risk reversal from parsed legs.

    Risk reversal structure:
    - 4 legs total
    - 3 distinct strikes (low, middle/ATM, high)
    - Middle strike has payer + receiver (ATM straddle, smaller notional)
    - Low strike is OTM receiver (put wing) - forced regardless of SDR label
    - High strike is OTM payer (call wing) - forced regardless of SDR label
    """
    if len(strikes) != 4:
        raise ValueError(f"Risk reversal must have 4 legs, got {len(strikes)}")

    strike_groups = {}
    for i, strike in enumerate(strikes):
        bucket = round(strike / strike_tolerance) if strike_tolerance > 0 else strike
        if bucket not in strike_groups:
            strike_groups[bucket] = []
        strike_groups[bucket].append(i)

    if len(strike_groups) != 3:
        raise ValueError(f"Risk reversal must have 3 distinct strikes, got {len(strike_groups)}")

    sorted_groups = sorted(
        strike_groups.items(),
        key=lambda x: np.mean([strikes[i] for i in x[1]]),
    )

    low_group = sorted_groups[0][1]
    mid_group = sorted_groups[1][1]
    high_group = sorted_groups[2][1]

    if len(mid_group) != 2:
        raise ValueError(f"ATM strike should have 2 legs (payer+receiver), got {len(mid_group)}")

    atm_strike = np.mean([strikes[i] for i in mid_group])
    low_strike = np.mean([strikes[i] for i in low_group])
    high_strike = np.mean([strikes[i] for i in high_group])

    # Find ATM payer and receiver premiums by product_type
    atm_payer_premium = None
    atm_receiver_premium = None
    atm_notional = None
    for i in mid_group:
        pt = product_types[i].upper()
        if "PAYER" in pt:
            atm_payer_premium = premiums[i]
            atm_notional = abs(notionals[i])
        elif "RECEIVER" in pt:
            atm_receiver_premium = premiums[i]
            if atm_notional is None:
                atm_notional = abs(notionals[i])

    if atm_payer_premium is None or atm_receiver_premium is None:
        raise ValueError("ATM straddle must have both payer and receiver legs")

    # OTM wings: force low strike = receiver, high strike = payer
    # Always use the leg at that strike level, regardless of SDR product_type label
    low_idx = low_group[0]
    high_idx = high_group[0]

    # Extract premiums/notionals by strike level (not by product_type)
    otm_receiver_strike = low_strike
    otm_receiver_premium = premiums[low_idx]
    otm_receiver_notional = abs(notionals[low_idx])

    otm_payer_strike = high_strike
    otm_payer_premium = premiums[high_idx]
    otm_payer_notional = abs(notionals[high_idx])

    return (
        (atm_strike, atm_payer_premium, atm_receiver_premium),
        (otm_payer_strike, otm_payer_premium, otm_payer_notional),
        (otm_receiver_strike, otm_receiver_premium, otm_receiver_notional),
        atm_notional,
    )


def _identify_vertical_spread_structure(
    strikes: List[float],
    premiums: List[float],
    notionals: List[float],
    product_types: List[str],
) -> Tuple[
    Literal["PAYER_SPREAD", "RECEIVER_SPREAD"],
    Tuple[float, float, float],  # atm: (strike, premium, notional)
    Tuple[float, float, float],  # otm: (strike, premium, notional)
]:
    """
    Identify the structure of a vertical spread from parsed legs.

    Vertical spread structure:
    - 2 legs with different strikes
    - Same option type (both payers or both receivers)
    - ATM leg = closer to forward (higher premium for same notional)
    - OTM leg = further from forward (lower premium for same notional)

    For payer spreads: ATM is lower strike, OTM is higher strike
    For receiver spreads: ATM is higher strike, OTM is lower strike
    """
    if len(strikes) != 2:
        raise ValueError(f"Vertical spread must have 2 legs, got {len(strikes)}")

    pt_upper = [pt.upper() for pt in product_types]
    is_payer = ["PAYER" in pt for pt in pt_upper]
    is_receiver = ["RECEIVER" in pt for pt in pt_upper]

    if all(is_payer):
        spread_type = "PAYER_SPREAD"
    elif all(is_receiver):
        spread_type = "RECEIVER_SPREAD"
    else:
        raise ValueError(f"Vertical spread legs must be same type, got {product_types}")

    # For payer spread: lower strike = ATM (more ITM, higher premium)
    # For receiver spread: higher strike = ATM (more ITM, higher premium)
    if spread_type == "PAYER_SPREAD":
        if strikes[0] < strikes[1]:
            atm_idx, otm_idx = 0, 1
        else:
            atm_idx, otm_idx = 1, 0
    else:  # RECEIVER_SPREAD
        if strikes[0] > strikes[1]:
            atm_idx, otm_idx = 0, 1
        else:
            atm_idx, otm_idx = 1, 0

    atm = (strikes[atm_idx], premiums[atm_idx], abs(notionals[atm_idx]))
    otm = (strikes[otm_idx], premiums[otm_idx], abs(notionals[otm_idx]))

    return spread_type, atm, otm
