"""Tests for peak identification and migration tracking."""
import datetime
import pandas as pd
import numpy as np
import pytest

from RVUtils.StripPeak.peak_tracker import identify_peak, migration_events


def _make_strip() -> pd.DataFrame:
    """Synthetic strip: 5 dates, 6 contracts, peak migrates from C3 to C4."""
    contracts = [f"SR3{c}" for c in ["U26", "Z26", "H27", "M27", "U27", "Z27"]]
    data = {
        # rates: peak starts at M27, migrates to U27 on day 4
        contracts[0]: [3.80, 3.80, 3.80, 3.80, 3.80],
        contracts[1]: [3.90, 3.90, 3.90, 3.90, 3.90],
        contracts[2]: [4.00, 4.00, 4.00, 4.00, 4.00],
        contracts[3]: [4.10, 4.12, 4.14, 4.05, 4.05],  # peak days 1-3
        contracts[4]: [4.05, 4.08, 4.10, 4.15, 4.18],  # peak days 4-5
        contracts[5]: [3.95, 3.95, 3.95, 3.95, 3.95],
    }
    dates = pd.date_range("2026-08-18", periods=5, freq="B").date
    return pd.DataFrame(data, index=dates)


def test_identify_peak_basic():
    strip = _make_strip()
    peak = identify_peak(strip)
    assert len(peak) == 5
    assert peak["peak_contract"].iloc[0] == "SR3M27"
    assert peak["peak_contract"].iloc[-1] == "SR3U27"
    assert peak["is_interior"].all()  # none at endpoints


def test_peak_prominence():
    strip = _make_strip()
    peak = identify_peak(strip)
    # prominence = peak_rate - avg(neighbors)
    # day 1: M27=4.10, neighbors H27=4.00, U27=4.05 -> prom = 4.10 - 4.025 = 0.075
    assert abs(peak["prominence"].iloc[0] - 0.075) < 0.001


def test_migration_events():
    strip = _make_strip()
    peak = identify_peak(strip)
    events = migration_events(peak)
    assert len(events) == 1  # one migration: M27 -> U27
    assert events.iloc[0]["from_contract"] == "SR3M27"
    assert events.iloc[0]["to_contract"] == "SR3U27"
