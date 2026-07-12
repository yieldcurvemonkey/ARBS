# tests/test_pts_scale.py
from SDRUtils.core.pts_scale import spread_to_bp


def test_decimal_spreadover_to_bp():
    assert abs(spread_to_bp(-0.004239) - (-42.39)) < 0.01


def test_percent_spreadover_to_bp():
    assert abs(spread_to_bp(-0.422) - (-42.2)) < 0.01


def test_ambiguous_mid_returns_none():
    assert spread_to_bp(0.05) is None


def test_huge_returns_none():
    assert spread_to_bp(-50.0) is None


def test_zero_and_missing():
    assert spread_to_bp(0.0) == 0.0
    assert spread_to_bp(None) is None
    assert spread_to_bp(float("nan")) is None
