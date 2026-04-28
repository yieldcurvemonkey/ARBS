"""Unit tests for the pure-string SFR → IMM tenor transformation and the
``current_level_bp`` futures-snapshot reader."""

import numpy as np
import pandas as pd
import pytest

from RVUtils.SFRConvexScreener import Leg
from RVUtils.SFRConvexScreener._carry_roll import (
    current_level_bp,
    sfr_to_imm_tenor,
    structure_rolldown_bp,
)


def test_sfr_to_imm_tenor_z26():
    assert sfr_to_imm_tenor("SFRZ26") == "IMM_Z2026xIMM_H2027"


def test_sfr_to_imm_tenor_h27():
    assert sfr_to_imm_tenor("SFRH27") == "IMM_H2027xIMM_M2027"


def test_sfr_to_imm_tenor_z29_wrap():
    """Year wraps when month is December."""
    assert sfr_to_imm_tenor("SFRZ29") == "IMM_Z2029xIMM_H2030"


def test_sfr_to_imm_tenor_invalid_root_raises():
    with pytest.raises(ValueError):
        sfr_to_imm_tenor("ZZZ26")


def _trivial_futures_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"symbol": "SFRZ26", "rate": 3.50},
            {"symbol": "SFRH27", "rate": 3.40},
            {"symbol": "SFRM27", "rate": 3.30},
        ]
    ).set_index("symbol")


def test_current_level_outright():
    legs = (Leg("SFRZ26", 1.0, 96.5, 25),)
    assert abs(current_level_bp(legs, futures_df=_trivial_futures_df()) - 350.0) < 1e-9


def test_current_level_calendar():
    """Calendar weights (1, -1) on rates 3.50% and 3.40% → +0.10% × 100 = +10 bp."""
    legs = (Leg("SFRZ26", 1.0, 96.5, 25), Leg("SFRH27", -1.0, 96.6, 25))
    assert abs(current_level_bp(legs, futures_df=_trivial_futures_df()) - 10.0) < 1e-9


def test_current_level_butterfly_zero_when_perfectly_linear():
    """Fly weights (1, -2, 1) on rates 3.5, 3.4, 3.3 → 3.5 - 2*3.4 + 3.3 = 0."""
    legs = (
        Leg("SFRZ26", 1.0, 96.5, 25),
        Leg("SFRH27", -2.0, 96.6, 25),
        Leg("SFRM27", 1.0, 96.7, 25),
    )
    assert abs(current_level_bp(legs, futures_df=_trivial_futures_df())) < 1e-9


def test_current_level_returns_nan_when_missing_leg():
    legs = (Leg("UNKNOWN", 1.0, 96.5, 25),)
    assert np.isnan(current_level_bp(legs, futures_df=_trivial_futures_df()))


def test_structure_rolldown_returns_nan_when_curve_none():
    legs = (Leg("SFRZ26", 1.0, 96.5, 25),)
    assert np.isnan(
        structure_rolldown_bp(legs, curve_handle=None, curve_name="X", horizon="3m")
    )
