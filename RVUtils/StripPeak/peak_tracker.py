"""Identify the peak-rate contract in a strip and track its migration."""
from __future__ import annotations

import pandas as pd
import numpy as np


def identify_peak(strip_df: pd.DataFrame) -> pd.DataFrame:
    """For each date, find the contract with the highest implied rate.

    Parameters
    ----------
    strip_df : DataFrame
        Index = date, columns = SR3 symbols, values = rate (%).

    Returns
    -------
    DataFrame with columns:
        peak_contract, peak_rate, peak_idx, prominence, is_interior
    """
    cols = list(strip_df.columns)
    rates = strip_df.values  # (n_dates, n_contracts)
    peak_idx = np.argmax(rates, axis=1)
    peak_rate = rates[np.arange(len(rates)), peak_idx]
    peak_contract = [cols[i] for i in peak_idx]

    # prominence: peak_rate minus average of immediate neighbors
    prominence = np.full(len(rates), np.nan)
    is_interior = np.ones(len(rates), dtype=bool)
    for i, pi in enumerate(peak_idx):
        if pi == 0:
            # peak at front — only right neighbor
            prominence[i] = peak_rate[i] - rates[i, pi + 1]
            is_interior[i] = False
        elif pi == len(cols) - 1:
            # peak at back — only left neighbor
            prominence[i] = peak_rate[i] - rates[i, pi - 1]
            is_interior[i] = False
        else:
            avg_neighbors = (rates[i, pi - 1] + rates[i, pi + 1]) / 2
            prominence[i] = peak_rate[i] - avg_neighbors

    return pd.DataFrame(
        {
            "peak_contract": peak_contract,
            "peak_rate": peak_rate,
            "peak_idx": peak_idx,
            "prominence": prominence,
            "is_interior": is_interior,
        },
        index=strip_df.index,
    )


def migration_events(peak_df: pd.DataFrame) -> pd.DataFrame:
    """Return rows where the peak contract changed from the previous day."""
    shifted = peak_df["peak_contract"].shift(1)
    mask = (peak_df["peak_contract"] != shifted) & shifted.notna()
    events = peak_df[mask].copy()
    events["from_contract"] = shifted[mask].values
    events["to_contract"] = events["peak_contract"].values
    return events[["from_contract", "to_contract", "peak_rate", "prominence"]]
