"""Tape metrics for gap flies: leg ordering, structural risk (belly), and
summary rate (2*belly - front - back) must use forward_start_years, not
tenor_years, when all legs share the same tail tenor.
"""
import pandas as pd
import pytest

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import (
    _leg_order_series,
    _structural_risk,
    _compute_leg_summary,
)


def _gap_fly_group():
    """IMM_M2027/M2028/M2029 1Y gap fly (belly = M2028, 12K)."""
    return pd.DataFrame([
        dict(package_id="FLY_1", trade_id="W1_M2027", execution_timestamp="2026-05-29T15:58:51Z",
             tenor_years=1.0027, forward_start_years=1.05, risk=6000.0, fixed_rate=0.03882,
             other_payment_amount=None, package_type="FLY", trade_type="FLY"),
        dict(package_id="FLY_1", trade_id="BELLY_M2028", execution_timestamp="2026-05-29T15:58:51Z",
             tenor_years=1.0, forward_start_years=2.06, risk=12000.0, fixed_rate=0.03812,
             other_payment_amount=None, package_type="FLY", trade_type="FLY"),
        dict(package_id="FLY_1", trade_id="W2_M2029", execution_timestamp="2026-05-29T15:58:51Z",
             tenor_years=1.0, forward_start_years=3.06, risk=6000.0, fixed_rate=0.03843,
             other_payment_amount=None, package_type="FLY", trade_type="FLY"),
    ])


def test_leg_order_gap_fly_sorted_by_forward():
    g = _gap_fly_group()
    g["leg_order"] = _leg_order_series(g)
    ordered = g.sort_values("leg_order")
    assert ordered.iloc[0]["trade_id"] == "W1_M2027"
    assert ordered.iloc[1]["trade_id"] == "BELLY_M2028"
    assert ordered.iloc[2]["trade_id"] == "W2_M2029"


def test_structural_risk_gap_fly_uses_belly():
    g = _gap_fly_group()
    risk = pd.to_numeric(g["risk"])
    tenor_y = pd.to_numeric(g["tenor_years"])
    fwd_y = pd.to_numeric(g["forward_start_years"])
    sr = _structural_risk(risk, tenor_y, "FLY", forward_start_years=fwd_y)
    assert sr == pytest.approx(12000.0)


def test_summary_rate_gap_fly_ties_out():
    g = _gap_fly_group()
    result = _compute_leg_summary(g, "FLY", "FLY")
    # 2*belly - front - back = 2*0.03812 - 0.03882 - 0.03843 = -0.00101
    expected = 2 * 0.03812 - 0.03882 - 0.03843
    assert result["summary_rate"] == pytest.approx(expected, abs=1e-8)
    assert result["summary_risk"] == pytest.approx(12000.0)
