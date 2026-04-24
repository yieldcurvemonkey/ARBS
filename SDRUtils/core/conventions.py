"""
Day-count and timing conventions for SDR analytics.

Maps CFTC Part 43/45 Tech Spec Appendix C day-count codes (A001..A020, NARR)
to QuantLib DayCounter instances. Used by the enrichment pipeline to compute
year fractions that match external pricer conventions.

Reference: Part 43/45 v3.1 Tech Spec, Data Element [#53], Appendix C.
"""
from __future__ import annotations

from typing import Dict, Optional

import QuantLib as ql


# Each code maps to the closest QuantLib counter. `NARR` is a narrative code
# (the spec lets the RC describe the convention in plain text); callers must
# map it externally or use the currency-default fallback.
DAY_COUNT_TABLE: Dict[str, Optional[ql.DayCounter]] = {
    "A001": ql.Thirty360(ql.Thirty360.BondBasis),
    "A002": ql.Thirty360(ql.Thirty360.USA),
    "A003": ql.Thirty360(ql.Thirty360.USA),
    "A004": ql.Actual360(),
    "A005": ql.Actual365Fixed(),
    "A006": ql.ActualActual(ql.ActualActual.ISMA),
    "A007": ql.Thirty360(ql.Thirty360.EurobondBasis),
    "A008": ql.ActualActual(ql.ActualActual.ISDA),
    "A009": ql.ActualActual(ql.ActualActual.AFB),
    "A010": ql.ActualActual(ql.ActualActual.Bond),
    "A011": ql.Business252(),
    "A012": ql.Actual365Fixed(ql.Actual365Fixed.NoLeap),
    "A013": ql.Actual366(),
    "A014": ql.Thirty360(ql.Thirty360.Italian),
    "A015": ql.Thirty360(ql.Thirty360.German),
    "A016": ql.OneDayCounter(),
    "A017": ql.SimpleDayCounter(),
    "A018": ql.Actual365Fixed(),
    "A019": ql.Actual360(),
    "A020": ql.Thirty360(ql.Thirty360.BondBasis),
    "NARR": None,
}


def resolve_day_counter(
    code: Optional[str],
    fallback: ql.DayCounter,
) -> ql.DayCounter:
    """Resolve Appendix C day-count code to a QuantLib DayCounter.

    Args:
        code: Appendix C code (e.g. ``"A004"``), or ``None``/``"NARR"`` for
            narrative-specified day count (caller must map externally).
        fallback: DayCounter returned for ``None``, unknown, or ``NARR``
            codes. Typically the currency's default convention.

    Returns:
        Matching ``ql.DayCounter`` or ``fallback``.
    """
    if code is None:
        return fallback
    key = str(code).strip().upper()
    if not key or key == "NARR":
        return fallback
    mapped = DAY_COUNT_TABLE.get(key)
    if mapped is None:
        return fallback
    return mapped
