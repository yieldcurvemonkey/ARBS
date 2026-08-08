"""Planted-value tests for the smile surface interpolation."""
import math

import pandas as pd
import pytest

from RVUtils.StrikelessVol.straddle_book import SmileSurface


def _panel():
    rows = []
    for e_tok, e_yrs, base in (("1Y", 1.0, 80.0), ("2Y", 2.0, 70.0)):
        for off in (-100.0, 0.0, 100.0):
            rows.append({"expiry": e_tok, "tenor": "10Y", "offset_bp": off,
                         "vol_bp": base + 0.05 * abs(off), "expiry_yrs": e_yrs,
                         "tenor_yrs": 10.0})
    return pd.DataFrame(rows)


def test_on_grid_exact():
    s = SmileSurface(_panel(), tenor="10Y")
    assert s.vol(expiry_yrs=1.0, offset_bp=0.0) == pytest.approx(80.0)
    assert s.vol(expiry_yrs=2.0, offset_bp=100.0) == pytest.approx(75.0)


def test_offset_linear_hand_value():
    s = SmileSurface(_panel(), tenor="10Y")
    # halfway between 0 (80.0) and +100 (85.0) -> 82.5
    assert s.vol(expiry_yrs=1.0, offset_bp=50.0) == pytest.approx(82.5)


def test_log_expiry_interp_hand_value():
    s = SmileSurface(_panel(), tenor="10Y")
    # at sqrt(2) years, log weight is exactly 0.5 between 1y (80) and 2y (70)
    assert s.vol(expiry_yrs=math.sqrt(2.0), offset_bp=0.0) == pytest.approx(75.0)


def test_refuses_wing_extrapolation():
    s = SmileSurface(_panel(), tenor="10Y")
    with pytest.raises(ValueError, match="wing"):
        s.vol(expiry_yrs=1.0, offset_bp=150.0)


def test_refuses_expiry_extrapolation():
    s = SmileSurface(_panel(), tenor="10Y")
    with pytest.raises(ValueError, match="term structure"):
        s.vol(expiry_yrs=0.5, offset_bp=0.0)


def test_missing_tenor_raises():
    with pytest.raises(KeyError):
        SmileSurface(_panel(), tenor="5Y")
