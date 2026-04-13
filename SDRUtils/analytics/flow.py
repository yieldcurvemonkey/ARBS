"""
Trade flow decomposition and classification.

Provides functions to classify SDR trades by economic type (outright, curve,
fly, spreadover, etc.), forward-start period, execution venue, and CCP.
"""

from __future__ import annotations

from typing import Optional, Set

import pandas as pd

from .filters import D2D_PLATFORMS

# ---------------------------------------------------------------------------
# Forward-start bucket labels (ordered)
# ---------------------------------------------------------------------------

FORWARD_LABELS: list[str] = [
    "spot", "1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "2Y", "3Y+",
]


# ---------------------------------------------------------------------------
# Trade type classification
# ---------------------------------------------------------------------------


def assign_trade_type(row: pd.Series) -> str:
    """Classify a trade row into its economic trade type.

    Examines ``package_type``, ``is_spreadover``, and ``special_tenor_type``
    to determine whether the trade is a package leg, a spreadover, a
    special-tenor variant, or a plain outright.

    Args:
        row: A single row (or dict-like) with keys ``package_type``,
            ``is_spreadover``, and ``special_tenor_type``.

    Returns:
        One of ``OUTRIGHT``, ``CURVE``, ``FLY``, ``SPREADOVER``, ``MAC``,
        ``IMM``, ``FOMC``, ``MATCHED_MATURITY``, or ``INVOICE_SWAP``.
    """
    pkg = str(row.get("package_type", "")).upper()
    if pkg in ("CURVE", "FLY"):
        return pkg
    if row.get("is_spreadover", False):
        return "SPREADOVER"
    st = str(row.get("special_tenor_type", "STANDARD")).upper()
    if st in ("MAC", "IMM", "FOMC", "MATCHED_MATURITY", "INVOICE_SWAP"):
        return st
    return "OUTRIGHT"


# ---------------------------------------------------------------------------
# Forward-start bucketing
# ---------------------------------------------------------------------------


def bucket_forward_start(label: object) -> str:
    """Map a forward-start label to a standard bucket.

    Args:
        label: The raw ``forward_label`` value (e.g. ``"3M"``, ``"2Y"``,
            ``None``).  ``NaN`` and ``"spot"`` map to ``"spot"``.

    Returns:
        One of the values in :data:`FORWARD_LABELS`.
    """
    if pd.isna(label) or str(label).lower() == "spot":
        return "spot"
    s = str(label)
    if s in FORWARD_LABELS:
        return s
    # Fallback: anything not in the known list is 3Y+
    return "3Y+"


# ---------------------------------------------------------------------------
# Venue classification
# ---------------------------------------------------------------------------


def classify_venue(
    platform_id: object,
    d2d_platforms: Optional[Set[str]] = None,
) -> str:
    """Classify a platform identifier as dealer-to-dealer or dealer-to-client.

    Args:
        platform_id: The ``platform_identifier`` value from the SDR record.
        d2d_platforms: Set of known D2D platform codes.  Defaults to
            :data:`~SDRUtils.analytics.filters.D2D_PLATFORMS`.

    Returns:
        ``"D2D"`` or ``"D2C"``.
    """
    if d2d_platforms is None:
        d2d_platforms = D2D_PLATFORMS
    pid = str(platform_id).upper().strip()
    return "D2D" if pid in d2d_platforms else "D2C"


# ---------------------------------------------------------------------------
# CCP inference
# ---------------------------------------------------------------------------


def infer_ccp(row: pd.Series) -> str:
    """Infer the central counterparty from the platform identifier.

    CME platforms contain ``"CME"`` in their identifier; everything else
    defaults to LCH (the dominant CCP for USD cleared swaps).

    Args:
        row: A single row (or dict-like) with key ``platform_identifier``.

    Returns:
        ``"CME"`` or ``"LCH"``.
    """
    platform = str(row.get("platform_identifier", "")).upper()
    if "CME" in platform:
        return "CME"
    return "LCH"
