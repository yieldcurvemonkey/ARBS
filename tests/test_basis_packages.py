"""Tests for basis-aware package detection."""

import pandas as pd
import pytest

from SDRUtils.packages.basis import detect_basis_packages_df, BasisPackageType


def _make_basis_trades(overrides_list):
    """Create a DataFrame of basis swap trades for testing."""
    base = {
        "trade_id": 0,
        "execution_timestamp": "2026-03-09 16:00:00",
        "tenor_label": "5Y",
        "effective_date": "2026-03-11",
        "forward_label": "spot",
        "basis_type": "SOFR_FF",
        "product_type": "OIS_SWAP",
        "estimated_pv01": 500.0,
        "package_type": "OUTRIGHT",
        "Platform identifier": "LCH",
        "Cleared": "Y",
    }
    rows = []
    for i, ovr in enumerate(overrides_list):
        row = {**base, "trade_id": i, **ovr}
        rows.append(row)
    return pd.DataFrame(rows)


class TestBasisCurveDetection:
    def test_two_sofr_ff_different_tenors_same_window(self):
        """Two SOFR/FF basis swaps with different tenors within 60s = BASIS_CURVE."""
        df = _make_basis_trades([
            {"tenor_label": "2Y", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "execution_timestamp": "2026-03-09 16:00:30"},
        ])
        result = detect_basis_packages_df(df)
        assert (result["package_type"] == BasisPackageType.BASIS_CURVE.value).all()
        assert result["package_id"].iloc[0] == result["package_id"].iloc[1]

    def test_same_tenor_not_packaged(self):
        """Same tenor should not be detected as a package."""
        df = _make_basis_trades([
            {"tenor_label": "5Y", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "5Y", "execution_timestamp": "2026-03-09 16:00:10"},
        ])
        result = detect_basis_packages_df(df)
        assert not (result["package_type"] == BasisPackageType.BASIS_CURVE.value).any()

    def test_outside_time_window_not_packaged(self):
        """Trades beyond 60s window should not be packaged."""
        df = _make_basis_trades([
            {"tenor_label": "2Y", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "execution_timestamp": "2026-03-09 16:02:00"},
        ])
        result = detect_basis_packages_df(df)
        assert not (result["package_type"] == BasisPackageType.BASIS_CURVE.value).any()

    def test_different_basis_type_not_packaged(self):
        """Different basis types should not be packaged together."""
        df = _make_basis_trades([
            {"tenor_label": "2Y", "basis_type": "SOFR_FF", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "basis_type": "CMS", "execution_timestamp": "2026-03-09 16:00:10"},
        ])
        result = detect_basis_packages_df(df)
        assert not (result["package_type"] == BasisPackageType.BASIS_CURVE.value).any()

    def test_different_effective_dates_not_packaged(self):
        """Different effective dates should not be packaged."""
        df = _make_basis_trades([
            {"tenor_label": "2Y", "effective_date": "2026-03-11", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "effective_date": "2026-06-11", "execution_timestamp": "2026-03-09 16:00:10"},
        ])
        result = detect_basis_packages_df(df)
        assert not (result["package_type"] == BasisPackageType.BASIS_CURVE.value).any()


class TestBasisFlyDetection:
    def test_three_legs_detected_as_fly(self):
        """Three basis swaps in window with different tenors = BASIS_FLY."""
        df = _make_basis_trades([
            {"tenor_label": "2Y", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "5Y", "execution_timestamp": "2026-03-09 16:00:10"},
            {"tenor_label": "10Y", "execution_timestamp": "2026-03-09 16:00:20"},
        ])
        result = detect_basis_packages_df(df)
        assert (result["package_type"] == BasisPackageType.BASIS_FLY.value).all()
        assert result["package_id"].nunique() == 1


class TestBasisPackagesEmpty:
    def test_empty_df(self):
        result = detect_basis_packages_df(pd.DataFrame())
        assert result.empty

    def test_no_basis_trades(self):
        df = pd.DataFrame({
            "trade_id": [1, 2],
            "execution_timestamp": ["2026-03-09 16:00:00", "2026-03-09 16:00:10"],
            "tenor_label": ["2Y", "10Y"],
            "basis_type": [None, None],
            "package_type": ["OUTRIGHT", "OUTRIGHT"],
        })
        result = detect_basis_packages_df(df)
        assert not (result["package_type"] == BasisPackageType.BASIS_CURVE.value).any()
