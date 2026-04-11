"""Tests for V2-aware package detection (rate_index separation, tenor-segment time windows)."""

import pandas as pd
import pytest

from SDRUtils.packages.curve import detect_curve_trades_df
from SDRUtils.packages.fly import detect_fly_trades_df


def _make_v2_trades(overrides_list):
    """Create DataFrame with V2 columns for curve/fly testing."""
    base = {
        "trade_id": 0,
        "execution_timestamp": "2026-03-09 16:00:00",
        "product_type": "OIS_SWAP",
        "estimated_pv01": 500.0,
        "tenor_label": "5Y",
        "tenor_years": 5.0,
        "effective_date": "2026-03-11",
        "forward_label": "spot",
        "forward_start_years": 0.0,
        "notional_currency": "USD",
        "UPI Underlier Name": "USD-SOFR",
        "Platform identifier": "LCH",
        "Cleared": "Y",
        "package_type": "OUTRIGHT",
        # V2 columns
        "rate_index": "SOFR",
        "tenor_segment": "MEDIUM",
        "linear_product_type": "OIS",
    }
    rows = []
    for i, ovr in enumerate(overrides_list):
        row = {**base, "trade_id": i, **ovr}
        rows.append(row)
    return pd.DataFrame(rows)


# ── Curve Detection ──────────────────────────────────────────────────


class TestV2CurveDetection:
    def test_same_rate_index_matches_curve(self):
        """Two SOFR trades, different tenors, same PV01 → CURVE."""
        df = _make_v2_trades([
            {"tenor_label": "2Y", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "execution_timestamp": "2026-03-09 16:00:30"},
        ])
        result = detect_curve_trades_df(df)
        assert (result["package_type"] == "CURVE").all()

    def test_cross_rate_index_no_curve(self):
        """SOFR + FF should NOT match as a curve."""
        df = _make_v2_trades([
            {"tenor_label": "2Y", "rate_index": "SOFR", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "rate_index": "FED_FUNDS", "execution_timestamp": "2026-03-09 16:00:10"},
        ])
        result = detect_curve_trades_df(df)
        assert not (result["package_type"] == "CURVE").any()

    def test_short_segment_30s_matches(self):
        """Two SHORT trades 25s apart → should match (within 30s window)."""
        df = _make_v2_trades([
            {"tenor_label": "1Y", "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "2Y", "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:25"},
        ])
        result = detect_curve_trades_df(df)
        assert (result["package_type"] == "CURVE").all()

    def test_short_segment_45s_no_match(self):
        """Two SHORT trades 45s apart → should NOT match (exceeds 30s)."""
        df = _make_v2_trades([
            {"tenor_label": "1Y", "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "2Y", "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:45"},
        ])
        result = detect_curve_trades_df(df)
        assert not (result["package_type"] == "CURVE").any()

    def test_mixed_segment_uses_wider_window(self):
        """SHORT + MEDIUM at 50s → should match (uses 60s window)."""
        df = _make_v2_trades([
            {"tenor_label": "2Y", "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "tenor_segment": "MEDIUM", "execution_timestamp": "2026-03-09 16:00:50"},
        ])
        result = detect_curve_trades_df(df)
        assert (result["package_type"] == "CURVE").all()

    def test_medium_segment_60s_matches(self):
        """Two MEDIUM trades 55s apart → should match."""
        df = _make_v2_trades([
            {"tenor_label": "5Y", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "execution_timestamp": "2026-03-09 16:00:55"},
        ])
        result = detect_curve_trades_df(df)
        assert (result["package_type"] == "CURVE").all()

    def test_backward_compat_no_v2_columns(self):
        """Trades without rate_index/tenor_segment → old behavior with 60s window."""
        df = _make_v2_trades([
            {"tenor_label": "2Y", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "execution_timestamp": "2026-03-09 16:00:55"},
        ])
        # Drop V2 columns
        df = df.drop(columns=["rate_index", "tenor_segment", "linear_product_type"])
        result = detect_curve_trades_df(df)
        assert (result["package_type"] == "CURVE").all()

    def test_nan_rate_index_no_cross_match(self):
        """NaN rate_index should not match with SOFR (string <NA> != 'SOFR')."""
        df = _make_v2_trades([
            {"tenor_label": "2Y", "rate_index": pd.NA, "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "10Y", "rate_index": "SOFR", "execution_timestamp": "2026-03-09 16:00:10"},
        ])
        result = detect_curve_trades_df(df)
        assert not (result["package_type"] == "CURVE").any()


# ── Fly Detection ────────────────────────────────────────────────────


def _make_fly_trades(overrides_list):
    """Create DataFrame with 3-leg butterfly structure + V2 columns."""
    base = {
        "trade_id": 0,
        "execution_timestamp": "2026-03-09 16:00:00",
        "product_type": "OIS_SWAP",
        "estimated_pv01": 500.0,
        "tenor_label": "5Y",
        "tenor_years": 5.0,
        "effective_date": "2026-03-11",
        "forward_label": "spot",
        "forward_start_years": 0.0,
        "notional_currency": "USD",
        "UPI Underlier Name": "USD-SOFR",
        "Platform identifier": "LCH",
        "Cleared": "Y",
        "package_type": "OUTRIGHT",
        "rate_index": "SOFR",
        "tenor_segment": "MEDIUM",
    }
    rows = []
    for i, ovr in enumerate(overrides_list):
        row = {**base, "trade_id": i, **ovr}
        rows.append(row)
    return pd.DataFrame(rows)


class TestV2FlyDetection:
    """Fly tests use tenors within ±2Y of belly (algorithm searches ±8 tenor buckets at 0.25Y)."""

    def test_same_rate_index_matches_fly(self):
        """Three SOFR trades in butterfly structure → FLY.
        Belly must be last chronologically for algorithm to find both wings."""
        df = _make_fly_trades([
            {"tenor_label": "3Y", "tenor_years": 3.0, "estimated_pv01": 250.0,
             "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "7Y", "tenor_years": 7.0, "estimated_pv01": 250.0,
             "execution_timestamp": "2026-03-09 16:00:05"},
            {"tenor_label": "5Y", "tenor_years": 5.0, "estimated_pv01": 500.0,
             "execution_timestamp": "2026-03-09 16:00:10"},
        ])
        result = detect_fly_trades_df(df)
        assert (result["package_type"] == "FLY").all()

    def test_mixed_rate_index_no_fly(self):
        """Belly SOFR, one wing FF → should NOT detect FLY."""
        df = _make_fly_trades([
            {"tenor_label": "3Y", "tenor_years": 3.0, "estimated_pv01": 250.0,
             "rate_index": "SOFR", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "7Y", "tenor_years": 7.0, "estimated_pv01": 250.0,
             "rate_index": "FED_FUNDS", "execution_timestamp": "2026-03-09 16:00:05"},
            {"tenor_label": "5Y", "tenor_years": 5.0, "estimated_pv01": 500.0,
             "rate_index": "SOFR", "execution_timestamp": "2026-03-09 16:00:10"},
        ])
        result = detect_fly_trades_df(df)
        assert not (result["package_type"] == "FLY").any()

    def test_short_segment_30s_fly(self):
        """All SHORT within 25s → FLY detected. Belly last."""
        df = _make_fly_trades([
            {"tenor_label": "6M", "tenor_years": 0.5, "estimated_pv01": 50.0,
             "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "18M", "tenor_years": 1.5, "estimated_pv01": 50.0,
             "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:05"},
            {"tenor_label": "1Y", "tenor_years": 1.0, "estimated_pv01": 100.0,
             "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:10"},
        ])
        result = detect_fly_trades_df(df)
        assert (result["package_type"] == "FLY").all()

    def test_short_segment_45s_no_fly(self):
        """All SHORT, belly 45s after first wing → should NOT match."""
        df = _make_fly_trades([
            {"tenor_label": "6M", "tenor_years": 0.5, "estimated_pv01": 50.0,
             "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "18M", "tenor_years": 1.5, "estimated_pv01": 50.0,
             "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:05"},
            {"tenor_label": "1Y", "tenor_years": 1.0, "estimated_pv01": 100.0,
             "tenor_segment": "SHORT", "execution_timestamp": "2026-03-09 16:00:45"},
        ])
        result = detect_fly_trades_df(df)
        assert not (result["package_type"] == "FLY").any()

    def test_backward_compat_fly_no_v2_columns(self):
        """Trades without V2 columns → old behavior. Belly last."""
        df = _make_fly_trades([
            {"tenor_label": "3Y", "tenor_years": 3.0, "estimated_pv01": 250.0,
             "execution_timestamp": "2026-03-09 16:00:00"},
            {"tenor_label": "7Y", "tenor_years": 7.0, "estimated_pv01": 250.0,
             "execution_timestamp": "2026-03-09 16:00:05"},
            {"tenor_label": "5Y", "tenor_years": 5.0, "estimated_pv01": 500.0,
             "execution_timestamp": "2026-03-09 16:00:10"},
        ])
        df = df.drop(columns=["rate_index", "tenor_segment"])
        result = detect_fly_trades_df(df)
        assert (result["package_type"] == "FLY").all()
