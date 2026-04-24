"""CFTC §43.4(f) notional cap-band validator.

The cap the CFTC applies before public dissemination is a function of
original tenor. Reporting a capped notional that exceeds the band for
the swap's tenor is a compliance signal — the cap should have been
applied server-side, so the reported capped value is telling us the
notional was miscategorised or the reporting party misapplied the cap.

Reference: 17 CFR §43.4(f)(1)-(3), Dollar notional caps schedule.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

# §43.4(f) cap schedule for IRS (USD-denominated). Values in USD.
# Rows: (upper_tenor_years_exclusive, cap_usd). Rows are in order; pick
# the first whose tenor threshold is > the trade's original tenor.
_CAP_SCHEDULE_USD = (
    (2.0, 250_000_000.0),        # 0 - 2Y: $250M
    (10.0, 100_000_000.0),       # 2 - 10Y: $100M
    (30.0, 75_000_000.0),        # 10 - 30Y: $75M
    (float("inf"), 75_000_000.0) # 30Y+: $75M
)


def cap_for_tenor(tenor_years: float) -> float:
    """Return the §43.4(f) cap applicable to a swap of the given tenor."""
    for upper, cap in _CAP_SCHEDULE_USD:
        if tenor_years < upper:
            return cap
    return _CAP_SCHEDULE_USD[-1][1]


def validate_cap_band(
    notional: Optional[float],
    tenor_years: Optional[float],
    is_capped: bool,
) -> bool:
    """Return True if the reported notional violates the cap band.

    A violation occurs when ``is_capped=True`` and the reported value
    exceeds the expected cap for that tenor — which means either the
    cap was never applied (compliance breach) or the notional was
    bucketed under the wrong tenor.

    ``notional`` for an uncapped trade is irrelevant to this check.
    """
    if not is_capped:
        return False
    if notional is None or pd.isna(notional):
        return False
    if tenor_years is None or pd.isna(tenor_years):
        return False
    cap = cap_for_tenor(float(tenor_years))
    # A capped reported notional that's well above the cap band is a
    # violation. Permit 1% over to absorb rounding in the reported value.
    tolerance = 1.01
    return float(notional) > cap * tolerance


def enrich_cap_band_column(df: pd.DataFrame) -> pd.DataFrame:
    """Materialize ``cap_band_violation`` bool on a DataFrame.

    Reads ``notional``, ``tenor_years``, ``is_notional_capped`` /
    ``is_capped``. Missing inputs yield False (no violation reported).
    """
    notional = df.get("notional")
    tenor = df.get("tenor_years")
    is_capped = (
        df.get("is_notional_capped")
        if "is_notional_capped" in df.columns
        else df.get("is_capped")
    )
    if notional is None or tenor is None or is_capped is None:
        df["cap_band_violation"] = False
        return df

    flags = []
    for i in range(len(df)):
        n = notional.iat[i] if i < len(notional) else None
        t = tenor.iat[i] if i < len(tenor) else None
        c = bool(is_capped.iat[i]) if i < len(is_capped) and pd.notna(is_capped.iat[i]) else False
        flags.append(validate_cap_band(n, t, c))
    df["cap_band_violation"] = flags
    return df
