"""Reset-frequency anomaly detection (N4).

SOFR compounds daily; ESTR compounds daily; SONIA compounds daily. A
SOFR-underlier trade reporting a YEAR+1 reset frequency is either a
mislabeled product (not a SOFR OIS) or a misapplied reset convention.
Surface as a compliance signal rather than dropping the trade.
"""
from __future__ import annotations

import pandas as pd


_OIS_UNDERLIERS = {
    "USD-SOFR-COMPOUND",
    "USD-SOFR-OIS COMPOUND",
    "EUR-ESTR-COMPOUND",
    "GBP-SONIA-COMPOUND",
    "CHF-SARON-COMPOUND",
    "JPY-TONA-COMPOUND",
}


def is_frequency_anomaly(
    upi_underlier: object,
    reset_freq: object,
) -> bool:
    """Return True when the reset frequency doesn't match a daily OIS underlier.

    Args:
        upi_underlier: Value of ``upi_underlier_name`` / UPI Underlier Name.
        reset_freq: Value of ``upi_reset_freq`` (e.g. ``"1D"``, ``"1Y"``).

    Returns:
        True if underlier is daily-compounding but reset frequency is
        ``1Y`` / ``YEAR+1``. False otherwise.
    """
    if upi_underlier is None or (isinstance(upi_underlier, float) and pd.isna(upi_underlier)):
        return False
    if reset_freq is None or (isinstance(reset_freq, float) and pd.isna(reset_freq)):
        return False

    underlier = str(upi_underlier).strip().upper()
    freq = str(reset_freq).strip().upper()

    # Only daily-compounded OIS underliers are in scope.
    is_ois = any(u in underlier for u in _OIS_UNDERLIERS) or underlier.endswith("COMPOUND")
    if not is_ois:
        return False

    # A yearly reset on an OIS underlier is the anomaly.
    return freq in {"1Y", "YEAR+1", "YEAR1", "YEARLY", "ANNUAL"}


def enrich_frequency_anomaly_column(df: pd.DataFrame) -> pd.DataFrame:
    """Materialize ``frequency_anomaly`` bool on a DataFrame."""
    underlier_col = (
        "upi_underlier_name"
        if "upi_underlier_name" in df.columns
        else "UPI Underlier Name"
        if "UPI Underlier Name" in df.columns
        else None
    )
    freq_col = (
        "upi_reset_freq"
        if "upi_reset_freq" in df.columns
        else None
    )
    if underlier_col is None or freq_col is None:
        df["frequency_anomaly"] = False
        return df
    flags = []
    for i in range(len(df)):
        flags.append(
            is_frequency_anomaly(df[underlier_col].iat[i], df[freq_col].iat[i])
        )
    df["frequency_anomaly"] = flags
    return df
