"""
Tests for swaption package detection.

Covers the trader-provided examples:
1. BILT "premium empty / package price filled" scenario
2. Identical timestamp multi-leg packages
3. The 30-second-apart linked packages (9m1y vs 1y1y)
4. Random single-leg flow doesn't over-trigger
"""

import datetime
import pytest
import pandas as pd
import numpy as np

from SDRUtils.packages.swaption_packages import (
    SwaptionPackageDetectionConfig,
    detect_swaption_packages_df,
    detect_and_link_swaption_packages_df,
    link_swaption_packages,
    _vega_bucket,
    _time_bucket,
    _extract_effective_premium,
    _compute_package_id,
    _estimate_swaption_vega,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def config():
    """Default config for tests."""
    return SwaptionPackageDetectionConfig(
        time_window_seconds=300,
        vega_tolerance_pct=0.05,
        min_legs=2,
    )


@pytest.fixture
def bilt_vega_curve_package_df():
    """
    Example: 4y5y vs 2y5y vega curve trade on BILT.

    From trader notes:
    - 4y5y (230mm k=4.025) vs 2y5y (470mm k=3.981)
    - platform = BILT
    - 2 of the 4 have package indicator = Y
    - all premiums are zero but package price is not
    - timestamps are identical
    - vega of the straddles is *very* similar

    This is an example of a customer-facing vega RV trade.
    """
    base_ts = pd.Timestamp("2026-01-06 14:30:00", tz="UTC")

    # Approximate vega for similar vega trades
    # 4y5y: ~230mm notional, 4y expiry -> vega ≈ 230mm * sqrt(4) * 0.01 = 4.6mm
    # 2y5y: ~470mm notional, 2y expiry -> vega ≈ 470mm * sqrt(2) * 0.01 = 6.6mm
    # For matching, we'll use similar vegas

    return pd.DataFrame([
        {
            "trade_id": "T001",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 230_000_000,
            "strike": 4.025,
            "tenor_years": 5.0,
            "forward_start_years": 4.0,  # 4y5y
            "premium": 0.0,
            "Package transaction price": 125000.0,
            "Package indicator": True,
        },
        {
            "trade_id": "T002",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts,  # Identical timestamp
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 230_000_000,
            "strike": 4.025,
            "tenor_years": 5.0,
            "forward_start_years": 4.0,
            "premium": 0.0,
            "Package transaction price": 125000.0,
            "Package indicator": True,
        },
        {
            "trade_id": "T003",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,  # Identical timestamp
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 470_000_000,
            "strike": 3.981,
            "tenor_years": 5.0,
            "forward_start_years": 2.0,  # 2y5y
            "premium": 0.0,
            "Package transaction price": 250000.0,
            "Package indicator": False,
        },
        {
            "trade_id": "T004",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts,  # Identical timestamp
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 470_000_000,
            "strike": 3.981,
            "tenor_years": 5.0,
            "forward_start_years": 2.0,
            "premium": 0.0,
            "Package transaction price": 250000.0,
            "Package indicator": False,
        },
    ])


@pytest.fixture
def linked_packages_df():
    """
    Example: 9m1y vs 1y1y trades that were reported as separate packages.

    From trader notes:
    - Time stamps 30 seconds apart: 9:11:34 and 9:11:56
    - Both are curve trades on same platform
    - Similar vega exposure
    - The 9m1y and 1y1y were reported as separate packages but are linked
    """
    base_ts = pd.Timestamp("2026-01-06 09:11:34", tz="UTC")

    return pd.DataFrame([
        # First "package" - 9m1y straddle
        {
            "trade_id": "L001",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.85,
            "tenor_years": 1.0,
            "forward_start_years": 0.75,  # 9m1y
            "premium": 48250.0,
            "Package transaction price": "",
            "Package indicator": True,
        },
        {
            "trade_id": "L002",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.85,
            "tenor_years": 1.0,
            "forward_start_years": 0.75,
            "premium": 48250.0,
            "Package transaction price": "",
            "Package indicator": True,
        },
        # Second "package" - 1y1y straddle (22 seconds later)
        {
            "trade_id": "L003",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=22),
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.82,
            "tenor_years": 1.0,
            "forward_start_years": 1.0,  # 1y1y
            "premium": 58750.0,
            "Package transaction price": "",
            "Package indicator": True,
        },
        {
            "trade_id": "L004",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=22),
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.82,
            "tenor_years": 1.0,
            "forward_start_years": 1.0,
            "premium": 58750.0,
            "Package transaction price": "",
            "Package indicator": True,
        },
    ])


@pytest.fixture
def random_single_leg_df():
    """
    Random single-leg trades that should NOT be grouped.

    Tests that detection doesn't over-trigger on unrelated trades.
    """
    base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

    trades = []
    for i in range(10):
        trades.append({
            "trade_id": f"R{i:03d}",
            "product_type": "SWAPTION_PAYER" if i % 2 == 0 else "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts + pd.Timedelta(minutes=i * 15),  # 15 min apart
            "Platform identifier": f"PLAT{i % 3}",  # Different platforms
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": (i + 1) * 10_000_000,  # Different notionals
            "strike": 4.0 + i * 0.1,
            "tenor_years": float(i % 5 + 1),
            "forward_start_years": float(i % 3 + 1),
            "premium": 50000.0 * (i + 1),
            "Package transaction price": "",
            "Package indicator": False,
        })

    return pd.DataFrame(trades)


# =============================================================================
# Unit Tests for Helper Functions
# =============================================================================


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_vega_bucket_same_bucket(self):
        """Values within tolerance should be in same or adjacent bucket."""
        vega = np.array([1000.0, 1049.0, 1000.0])  # 4.9% difference
        buckets = _vega_bucket(vega, 0.05)
        # Should be in adjacent buckets at most
        assert np.abs(buckets[0] - buckets[1]) <= 1

    def test_vega_bucket_different_buckets(self):
        """Values far apart should be in different buckets."""
        vega = np.array([1000.0, 2000.0])  # 100% difference
        buckets = _vega_bucket(vega, 0.05)
        assert buckets[0] != buckets[1]
        assert abs(buckets[0] - buckets[1]) > 1

    def test_time_bucket(self):
        """Test time bucketing."""
        timestamps = np.array([1000, 1010, 1029, 1030, 1060])
        buckets = _time_bucket(timestamps, bucket_seconds=30)
        assert buckets[0] == buckets[1] == buckets[2]  # All in same 30s bucket
        assert buckets[3] != buckets[0]  # 1030 in next bucket
        assert buckets[4] != buckets[3]  # 1060 in different bucket

    def test_extract_effective_premium_prefer_premium(self):
        """Test premium extraction with prefer_premium mode."""
        config = SwaptionPackageDetectionConfig(price_field_mode="prefer_premium")
        row = pd.Series({
            "premium": 1000.0,
            "Package transaction price": 2000.0,
        })
        val, src = _extract_effective_premium(row, config)
        assert val == 1000.0
        assert src == "PREMIUM"

    def test_extract_effective_premium_fallback_to_package_price(self):
        """Test premium extraction falls back to package price when premium is zero."""
        config = SwaptionPackageDetectionConfig(price_field_mode="both")
        row = pd.Series({
            "premium": 0.0,
            "Package transaction price": 2000.0,
        })
        val, src = _extract_effective_premium(row, config)
        assert val == 2000.0
        assert src == "PKG_PRICE"

    def test_extract_effective_premium_none(self):
        """Test premium extraction when both fields are empty."""
        config = SwaptionPackageDetectionConfig(price_field_mode="both")
        row = pd.Series({
            "premium": "",
            "Package transaction price": "",
        })
        val, src = _extract_effective_premium(row, config)
        assert pd.isna(val)
        assert src == "NONE"

    def test_compute_package_id_deterministic(self):
        """Package ID should be deterministic for same inputs."""
        ids1 = ["T001", "T002", "T003"]
        ids2 = ["T003", "T001", "T002"]  # Different order

        pid1 = _compute_package_id(ids1, "BILT", 1000, "VEGA_BUCKETED_PACKAGE")
        pid2 = _compute_package_id(ids2, "BILT", 1000, "VEGA_BUCKETED_PACKAGE")

        # Should be same since IDs are sorted internally
        assert pid1 == pid2

    def test_compute_package_id_different_for_different_inputs(self):
        """Package ID should differ for different inputs."""
        pid1 = _compute_package_id(["T001"], "BILT", 1000, "TYPE_A")
        pid2 = _compute_package_id(["T002"], "BILT", 1000, "TYPE_A")
        assert pid1 != pid2

    def test_estimate_swaption_vega(self):
        """Test vega estimation fallback."""
        row = pd.Series({
            "notional": 100_000_000,
            "forward_start_years": 1.0,  # 1Y expiry
        })
        vega = _estimate_swaption_vega(row)
        # vega ≈ 100mm * sqrt(1) * 0.01 = 1mm
        assert 900_000 < vega < 1_100_000


# =============================================================================
# Integration Tests for Package Detection
# =============================================================================


class TestSwaptionPackageDetection:
    """Tests for main detection function."""

    def test_bilt_identical_timestamp_package(self, bilt_vega_curve_package_df, config):
        """
        Test detection of BILT vega curve package with identical timestamps.

        From trader notes: 4y5y vs 2y5y with identical timestamps and
        premium=0 but package_price filled.
        """
        result = detect_swaption_packages_df(
            bilt_vega_curve_package_df,
            config=config,
        )

        # Should detect as IMPLIED_PACKAGE_SAME_TIMESTAMP due to identical timestamps
        packaged = result[result["package_id"].notna()]
        assert len(packaged) > 0, "Should detect package"

        # Check package type
        assert "IMPLIED_PACKAGE_SAME_TIMESTAMP" in packaged["package_type"].values

        # Check package reason contains key info
        reason = packaged["package_reason"].iloc[0]
        assert "platform=BILT" in reason
        assert "legs=" in reason

        # Check effective_premium_source is PKG_PRICE (since premium was 0)
        assert (packaged["effective_premium_source"] == "PKG_PRICE").all()

    def test_random_single_legs_not_grouped(self, random_single_leg_df, config):
        """
        Test that random single-leg trades don't over-trigger detection.

        Trades that are:
        - 15 minutes apart (outside window)
        - Different platforms
        - Different notionals (different vega)

        Should NOT be grouped.
        """
        result = detect_swaption_packages_df(
            random_single_leg_df,
            config=config,
        )

        # No packages should be detected
        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 0, "Should not group unrelated trades"

    def test_linked_packages_time_proximity(self, linked_packages_df, config):
        """
        Test detection and linking of 9m1y vs 1y1y packages.

        From trader notes: 30 seconds apart, reported as separate packages
        but economically linked.
        """
        result = detect_and_link_swaption_packages_df(
            linked_packages_df,
            config=config,
        )

        # Should detect multiple packages (potentially linked)
        packaged = result[result["package_id"].notna()]
        assert len(packaged) > 0, "Should detect packages"

        # All 4 trades should be in packages (2 legs each)
        assert len(packaged) == 4

    def test_platform_filter_allowlist(self, bilt_vega_curve_package_df):
        """Test platform allowlist filtering."""
        config = SwaptionPackageDetectionConfig(
            platform_allowlist=["ISWBVTPSEEBGCD"],  # Not BILT
        )

        result = detect_swaption_packages_df(
            bilt_vega_curve_package_df,
            config=config,
        )

        # No packages should be detected since BILT is not in allowlist
        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 0

    def test_platform_filter_blocklist(self, bilt_vega_curve_package_df):
        """Test platform blocklist filtering."""
        config = SwaptionPackageDetectionConfig(
            platform_blocklist=["BILT"],
        )

        result = detect_swaption_packages_df(
            bilt_vega_curve_package_df,
            config=config,
        )

        # No packages should be detected since BILT is blocked
        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 0

    def test_vega_tolerance_strict(self, bilt_vega_curve_package_df):
        """Test with very strict vega tolerance."""
        config = SwaptionPackageDetectionConfig(
            vega_tolerance_pct=0.001,  # 0.1% tolerance
        )

        result = detect_swaption_packages_df(
            bilt_vega_curve_package_df,
            config=config,
        )

        # With strict tolerance, might not group all trades
        # But identical-notional legs should still group
        packaged = result[result["package_id"].notna()]
        # At minimum, the two 230mm legs should group
        assert len(packaged) >= 2

    def test_min_legs_3(self, linked_packages_df):
        """Test minimum legs requirement."""
        config = SwaptionPackageDetectionConfig(
            min_legs=3,  # Require 3 legs
        )

        result = detect_swaption_packages_df(
            linked_packages_df,
            config=config,
        )

        # With 2-leg packages, min_legs=3 should reduce detection
        # May detect 4-leg package or nothing
        packaged = result[result["package_id"].notna()]
        if len(packaged) > 0:
            # If detected, should have at least 3 legs
            assert packaged["package_legs_count"].min() >= 3

    def test_confidence_scoring(self, bilt_vega_curve_package_df, config):
        """Test that confidence scoring works."""
        result = detect_swaption_packages_df(
            bilt_vega_curve_package_df,
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) > 0

        # Confidence should be between 0 and 1
        assert (packaged["package_confidence"] >= 0).all()
        assert (packaged["package_confidence"] <= 1).all()

        # High confidence expected for identical timestamp + package indicator
        assert packaged["package_confidence"].max() > 0.3

    def test_package_reason_format(self, bilt_vega_curve_package_df, config):
        """Test package reason has expected format."""
        result = detect_swaption_packages_df(
            bilt_vega_curve_package_df,
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) > 0

        reason = packaged["package_reason"].iloc[0]

        # Should contain structured key=value pairs
        assert "platform=" in reason
        assert "time_delta_max=" in reason
        assert "legs=" in reason

    def test_empty_dataframe(self, config):
        """Test handling of empty dataframe."""
        empty_df = pd.DataFrame()
        result = detect_swaption_packages_df(empty_df, config=config)
        assert len(result) == 0


class TestSwaptionPackageLinking:
    """Tests for package linking functionality."""

    def test_link_packages_basic(self, linked_packages_df, config):
        """Test basic package linking."""
        # First detect
        detected = detect_swaption_packages_df(linked_packages_df, config=config)

        # Then link
        result = link_swaption_packages(detected, config=config)

        # Check for linked_package_id column
        assert "linked_package_id" in result.columns
        assert "linked_package_relation" in result.columns

    def test_no_link_different_platforms(self, config):
        """Packages on different platforms should not be linked."""
        base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

        df = pd.DataFrame([
            {
                "trade_id": "P001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "PLAT_A",
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 100_000_000,
                "tenor_years": 1.0,
                "forward_start_years": 1.0,
                "premium": 50000.0,
            },
            {
                "trade_id": "P002",
                "product_type": "SWAPTION_RECEIVER",
                "execution_timestamp": base_ts,
                "Platform identifier": "PLAT_A",
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 100_000_000,
                "tenor_years": 1.0,
                "forward_start_years": 1.0,
                "premium": 50000.0,
            },
            {
                "trade_id": "P003",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts + pd.Timedelta(seconds=30),
                "Platform identifier": "PLAT_B",  # Different platform
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 100_000_000,
                "tenor_years": 1.0,
                "forward_start_years": 1.0,
                "premium": 50000.0,
            },
            {
                "trade_id": "P004",
                "product_type": "SWAPTION_RECEIVER",
                "execution_timestamp": base_ts + pd.Timedelta(seconds=30),
                "Platform identifier": "PLAT_B",
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 100_000_000,
                "tenor_years": 1.0,
                "forward_start_years": 1.0,
                "premium": 50000.0,
            },
        ])

        result = detect_and_link_swaption_packages_df(df, config=config)

        # Should have two separate packages, not linked
        linked = result[result["linked_package_id"].notna()]
        # No linking expected because different platforms
        assert len(linked) == 0


class TestSwaptionPackageDetector:
    """Tests for the detector class."""

    def test_detector_interface(self, bilt_vega_curve_package_df):
        """Test that detector implements interface correctly."""
        from SDRUtils.packages import SwaptionPackageDetector

        detector = SwaptionPackageDetector()

        assert detector.package_type == "SWAPTION_PACKAGE"
        assert hasattr(detector, "detect")
        assert hasattr(detector, "metadata")

    def test_detector_detect(self, bilt_vega_curve_package_df):
        """Test detector detect method."""
        from SDRUtils.packages import SwaptionPackageDetector

        detector = SwaptionPackageDetector()
        result = detector.detect(bilt_vega_curve_package_df)

        assert isinstance(result, pd.DataFrame)
        packaged = result[result["package_id"].notna()]
        assert len(packaged) > 0

    def test_detector_custom_config(self, bilt_vega_curve_package_df):
        """Test detector with custom config."""
        from SDRUtils.packages import SwaptionPackageDetector, SwaptionPackageDetectionConfig

        config = SwaptionPackageDetectionConfig(
            time_window_seconds=60,
            vega_tolerance_pct=0.02,
        )
        detector = SwaptionPackageDetector(config=config)

        metadata = detector.metadata()
        assert metadata["time_window_seconds"] == "60"
        assert metadata["vega_tolerance_pct"] == "0.02"


# =============================================================================
# Golden Snapshot Tests
# =============================================================================


class TestGoldenSnapshots:
    """
    Golden snapshot tests for the trader-provided examples.

    These encode the expected behavior for known patterns.
    """

    def test_4y5y_vs_2y5y_vega_rv_trade(self, bilt_vega_curve_package_df, config):
        """
        Golden test for the 4y5y vs 2y5y vega RV trade example.

        Expected:
        - All 4 legs detected as one package
        - Type: IMPLIED_PACKAGE_SAME_TIMESTAMP
        - Platform: BILT
        - Premium source: PKG_PRICE
        """
        result = detect_swaption_packages_df(
            bilt_vega_curve_package_df,
            config=config,
        )

        packaged = result[result["package_id"].notna()]

        # Assertions for golden behavior
        assert len(packaged) == 4, "All 4 legs should be in package"

        # All should have same package_id
        assert packaged["package_id"].nunique() == 1, "Should be single package"

        # Package type should be identical timestamp
        assert (packaged["package_type"] == "IMPLIED_PACKAGE_SAME_TIMESTAMP").all()

        # Effective premium source should be PKG_PRICE
        assert (packaged["effective_premium_source"] == "PKG_PRICE").all()

    def test_9m1y_vs_1y1y_curve_trade(self, linked_packages_df, config):
        """
        Golden test for the 9m1y vs 1y1y linked packages example.

        Expected:
        - 2 packages detected (2 legs each)
        - Potentially linked by time proximity
        """
        result = detect_and_link_swaption_packages_df(
            linked_packages_df,
            config=config,
        )

        packaged = result[result["package_id"].notna()]

        # All 4 legs should be in packages
        assert len(packaged) == 4

        # Should have either 1 package (all 4 grouped) or 2 packages (2+2)
        num_packages = packaged["package_id"].nunique()
        assert num_packages in [1, 2], f"Expected 1 or 2 packages, got {num_packages}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
