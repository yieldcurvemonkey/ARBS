"""
Compression analytics: detection, decomposition, and measurement.

~33% of SDR-reported trades are compression. Separating compression
from new-risk flow is essential for meaningful volume analysis.
"""
from __future__ import annotations

from typing import Tuple

import pandas as pd

from .filters import filter_new_risk


# ---------------------------------------------------------------------------
# Signal detection
# ---------------------------------------------------------------------------


def detect_compression_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add boolean columns identifying compression-related signals.

    Signals:
    - ``is_newt``: ``event_action`` == NEWT (new-risk candidate)
    - ``is_lifecycle``: ``event_action`` in TERM/CORR/MODI (non-NEWT)

    Args:
        df: DataFrame with optional ``event_action`` column.

    Returns:
        Copy of *df* with ``is_newt`` and ``is_lifecycle`` boolean columns
        added.
    """
    df = df.copy()

    if "event_action" in df.columns:
        action = df["event_action"].astype(str).str.upper()
        df["is_newt"] = action == "NEWT"
        df["is_lifecycle"] = action.isin({"TERM", "CORR", "MODI"})
    else:
        df["is_newt"] = True
        df["is_lifecycle"] = False

    return df


# ---------------------------------------------------------------------------
# Volume decomposition
# ---------------------------------------------------------------------------


def clean_volume_decomposition(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split trades into two non-overlapping volume categories.

    1. **clean_new_risk** -- NEWT trades (organic flow)
    2. **lifecycle** -- non-NEWT events (TERM/CORR/MODI compression)

    Uses :func:`~SDRUtils.analytics.filters.filter_new_risk` as the
    authoritative filter implementation.

    Args:
        df: DataFrame with optional ``event_action`` column.

    Returns:
        Tuple of ``(clean_new_risk, lifecycle)`` DataFrames. The two frames
        partition *df* with no overlap.
    """
    clean_new_risk = filter_new_risk(df)
    lifecycle = df[~df.index.isin(clean_new_risk.index)].copy()

    return clean_new_risk, lifecycle


# ---------------------------------------------------------------------------
# Compression ratio
# ---------------------------------------------------------------------------


def monthly_compression_ratio(
    raw_daily: pd.Series,
    clean_daily: pd.Series,
) -> pd.Series:
    """Monthly compression as a percentage of total reported volume.

    Resamples both series to month-end, then computes
    ``(1 - clean / raw) * 100``.  A result of 33 means 33 % of reported
    volume was non-new-risk (lifecycle/compression events).

    Args:
        raw_daily: Daily total DV01 series (all trades), indexed by date.
        clean_daily: Daily clean new-risk DV01, indexed by date.

    Returns:
        Monthly series of compression percentages, indexed by month-end
        dates.
    """
    raw = raw_daily.copy()
    raw.index = pd.to_datetime(raw.index)
    clean = clean_daily.copy()
    clean.index = pd.to_datetime(clean.index)

    monthly = pd.DataFrame(
        {
            "raw": raw.resample("ME").sum(),
            "clean": clean.resample("ME").sum(),
        }
    )
    return ((1 - monthly["clean"] / monthly["raw"]) * 100).rename(
        "compression_pct"
    )
