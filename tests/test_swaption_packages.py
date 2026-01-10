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
    detect_swaption_straddles_df,
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


# =============================================================================
# Straddle Detection Tests
# =============================================================================


@pytest.fixture
def straddle_df():
    """
    Example straddle: payer + receiver with same strike/expiry/tenor.
    """
    base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

    return pd.DataFrame([
        {
            "trade_id": "S001",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.50,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 5.0,
            "forward_start_years": 1.0,
            "premium": 125000.0,
            "Package indicator": False,
        },
        {
            "trade_id": "S002",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=30),  # 30 seconds later
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.50,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 5.0,
            "forward_start_years": 1.0,
            "premium": 125000.0,
            "Package indicator": False,
        },
    ])


@pytest.fixture
def straddle_with_tolerance_df():
    """
    Straddle with legs further apart in time.
    """
    base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

    return pd.DataFrame([
        {
            "trade_id": "ST001",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.50,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 5.0,
            "forward_start_years": 1.0,
            "premium": 125000.0,
        },
        {
            "trade_id": "ST002",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=90),  # 90 seconds later
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.50,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 5.0,
            "forward_start_years": 1.0,
            "premium": 125000.0,
        },
    ])


class TestStraddleDetection:
    """Tests for straddle detection functionality."""

    def test_basic_straddle_detection(self, straddle_df, config):
        """Test basic straddle detection with default tolerance."""
        result = detect_swaption_straddles_df(
            straddle_df,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            config=config,
        )

        # Both legs should be detected as straddle
        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 2, "Both legs should be in straddle"

        # Should be labeled as STRADDLE
        assert (packaged["package_type"] == "STRADDLE").all()

        # Should have same package_id
        assert packaged["package_id"].nunique() == 1

        # Should have 2 legs
        assert (packaged["package_legs_count"] == 2).all()

    def test_straddle_timestamp_tolerance(self, straddle_with_tolerance_df, config):
        """Test straddle detection with custom timestamp tolerance."""
        # With 60 second tolerance, should NOT detect (legs are 90s apart)
        result_60s = detect_swaption_straddles_df(
            straddle_with_tolerance_df,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            config=config,
        )
        packaged_60s = result_60s[result_60s["package_id"].notna()]
        assert len(packaged_60s) == 0, "Should not detect straddle with 60s tolerance"

        # With 120 second tolerance, should detect
        result_120s = detect_swaption_straddles_df(
            straddle_with_tolerance_df,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=120),
            config=config,
        )
        packaged_120s = result_120s[result_120s["package_id"].notna()]
        assert len(packaged_120s) == 2, "Should detect straddle with 120s tolerance"

    def test_straddle_strike_mismatch(self, config):
        """Test that different strikes don't form straddle."""
        base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

        df = pd.DataFrame([
            {
                "trade_id": "SM001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.50,
                "tenor_years": 5.0,
            },
            {
                "trade_id": "SM002",
                "product_type": "SWAPTION_RECEIVER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.75,  # Different strike
                "tenor_years": 5.0,
            },
        ])

        result = detect_swaption_straddles_df(
            df,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 0, "Different strikes should not form straddle"

    def test_straddle_notional_mismatch(self, config):
        """Test that very different notionals don't form straddle."""
        base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

        df = pd.DataFrame([
            {
                "trade_id": "NM001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.50,
                "tenor_years": 5.0,
            },
            {
                "trade_id": "NM002",
                "product_type": "SWAPTION_RECEIVER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 200_000_000,  # 2x different notional
                "strike": 4.50,
                "tenor_years": 5.0,
            },
        ])

        result = detect_swaption_straddles_df(
            df,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            notional_tolerance_pct=0.05,  # 5% tolerance
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 0, "Very different notionals should not form straddle"

    def test_straddle_confidence_scoring(self, straddle_df, config):
        """Test straddle confidence scoring."""
        result = detect_swaption_straddles_df(
            straddle_df,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 2

        # Confidence should be high for straddles
        assert packaged["package_confidence"].min() >= 0.8

    def test_straddle_reason_format(self, straddle_df, config):
        """Test straddle package reason format."""
        result = detect_swaption_straddles_df(
            straddle_df,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        reason = packaged["package_reason"].iloc[0]

        # Should contain strike and tenor info
        assert "strike=" in reason
        assert "tenor=" in reason
        assert "platform=" in reason

    def test_straddle_in_combined_detection(self, straddle_df, config):
        """Test that straddles are detected in combined detection."""
        result = detect_and_link_swaption_packages_df(
            straddle_df,
            config=config,
            detect_straddles=True,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 2

        # Should be STRADDLE type (detected first before vega bucketing)
        assert (packaged["package_type"] == "STRADDLE").all()

    def test_straddle_detection_disabled(self, straddle_df, config):
        """Test that straddles can be disabled in combined detection."""
        result = detect_and_link_swaption_packages_df(
            straddle_df,
            config=config,
            detect_straddles=False,
        )

        packaged = result[result["package_id"].notna()]

        # Straddle detection disabled - may or may not be detected by vega bucketing
        # But if detected, should NOT be STRADDLE type
        if len(packaged) > 0:
            assert not (packaged["package_type"] == "STRADDLE").any()


# =============================================================================
# Vertical Spread Detection Tests
# =============================================================================


@pytest.fixture
def vertical_spread_1x2_df():
    """
    Example 1x2 vertical spread: same tenor, different strikes, same option type.

    Structure:
    - 100mm 1Yx10Y payer @ 4.00% (long 1)
    - 200mm 1Yx10Y payer @ 4.50% (short 2)
    This is a bear payer spread (selling upside protection).
    """
    base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

    return pd.DataFrame([
        {
            "trade_id": "VS001",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.00,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,
            "forward_start_years": 1.0,
            "premium": 125000.0,
            "Package indicator": True,
        },
        {
            "trade_id": "VS002",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=5),
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 200_000_000,  # 2x notional = 1x2 spread
            "strike": 4.50,  # Higher strike
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,
            "forward_start_years": 1.0,
            "premium": 75000.0,
            "Package indicator": True,
        },
    ])


@pytest.fixture
def vertical_spread_1x1_receiver_df():
    """
    Example 1x1 receiver spread (bull spread).

    Structure:
    - 100mm 1Yx10Y receiver @ 4.00% (long)
    - 100mm 1Yx10Y receiver @ 3.50% (short)
    This is a bull receiver spread (expecting rates to fall, but not below 3.50%).
    """
    base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

    return pd.DataFrame([
        {
            "trade_id": "RS001",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.00,  # Higher strike (long)
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,
            "forward_start_years": 1.0,
            "premium": 150000.0,
        },
        {
            "trade_id": "RS002",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=10),
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,  # Same notional = 1x1
            "strike": 3.50,  # Lower strike (short)
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,
            "forward_start_years": 1.0,
            "premium": 80000.0,
        },
    ])


class TestVerticalSpreadDetection:
    """Tests for vertical spread detection functionality."""

    def test_1x2_payer_spread_detection(self, vertical_spread_1x2_df, config):
        """Test detection of 1x2 payer spread."""
        from SDRUtils.packages.swaption_packages import detect_swaption_vertical_spreads_df

        result = detect_swaption_vertical_spreads_df(
            vertical_spread_1x2_df,
            time_window_seconds=120,
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 2, "Both legs should be in spread"

        # Should be labeled as VERTICAL_SPREAD_1x2
        assert (packaged["package_type"] == "VERTICAL_SPREAD_1x2").all()

        # Should have same package_id
        assert packaged["package_id"].nunique() == 1

        # Should have 2 legs
        assert (packaged["package_legs_count"] == 2).all()

        # Reason should contain direction
        reason = packaged["package_reason"].iloc[0]
        assert "direction=" in reason
        assert "type=PAYER" in reason

    def test_1x1_receiver_spread_detection(self, vertical_spread_1x1_receiver_df, config):
        """Test detection of 1x1 receiver spread."""
        from SDRUtils.packages.swaption_packages import detect_swaption_vertical_spreads_df

        result = detect_swaption_vertical_spreads_df(
            vertical_spread_1x1_receiver_df,
            time_window_seconds=120,
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 2

        # Should be labeled as VERTICAL_SPREAD_1x1
        assert (packaged["package_type"] == "VERTICAL_SPREAD_1x1").all()

        # Reason should indicate RECEIVER and BULL direction
        reason = packaged["package_reason"].iloc[0]
        assert "type=RECEIVER" in reason

    def test_vertical_spread_not_straddle(self, config):
        """Test that payer+receiver is not detected as vertical spread."""
        base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

        df = pd.DataFrame([
            {
                "trade_id": "NS001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.00,
                "tenor_years": 10.0,
                "forward_start_years": 1.0,
            },
            {
                "trade_id": "NS002",
                "product_type": "SWAPTION_RECEIVER",  # Different type
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.50,
                "tenor_years": 10.0,
                "forward_start_years": 1.0,
            },
        ])

        from SDRUtils.packages.swaption_packages import detect_swaption_vertical_spreads_df

        result = detect_swaption_vertical_spreads_df(df, config=config)
        packaged = result[result["package_id"].notna()]

        # Should NOT detect as vertical spread (different option types)
        assert len(packaged) == 0

    def test_vertical_spread_different_tenor_not_detected(self, config):
        """Test that different underlying tenors don't form vertical spread."""
        base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

        df = pd.DataFrame([
            {
                "trade_id": "DT001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.00,
                "tenor_years": 10.0,  # 10Y tail
                "forward_start_years": 1.0,
                "expiration_date": pd.Timestamp("2027-01-06"),
            },
            {
                "trade_id": "DT002",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.50,
                "tenor_years": 30.0,  # Different tail
                "forward_start_years": 1.0,
                "expiration_date": pd.Timestamp("2027-01-06"),
            },
        ])

        from SDRUtils.packages.swaption_packages import detect_swaption_vertical_spreads_df

        result = detect_swaption_vertical_spreads_df(df, config=config)
        packaged = result[result["package_id"].notna()]

        # Should NOT detect (different tenors)
        assert len(packaged) == 0


# =============================================================================
# Conditional Curve Trade Detection Tests
# =============================================================================


@pytest.fixture
def conditional_steepener_df():
    """
    Example conditional steepener: 1Yx10Y vs 1Yx30Y payers.

    Structure:
    - 100mm 1Yx10Y payer @ 4.00% (long short-tail)
    - 50mm 1Yx30Y payer @ 4.25% (short long-tail, smaller due to DV01 weighting)

    This is a conditional steepener - profits if curve steepens in a selloff.
    """
    base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

    return pd.DataFrame([
        {
            "trade_id": "CS001",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.00,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,  # 10Y tail
            "forward_start_years": 1.0,
            "premium": 200000.0,
        },
        {
            "trade_id": "CS002",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=15),
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 50_000_000,  # Smaller (DV01 weighted)
            "strike": 4.25,
            "expiration_date": pd.Timestamp("2027-01-06"),  # Same expiry
            "tenor_years": 30.0,  # 30Y tail (20Y difference)
            "forward_start_years": 1.0,
            "premium": 150000.0,
        },
    ])


@pytest.fixture
def conditional_flattener_df():
    """
    Example conditional flattener: 1Yx10Y vs 1Yx30Y receivers.

    Structure:
    - 50mm 1Yx10Y receiver (short short-tail)
    - 100mm 1Yx30Y receiver (long long-tail)

    This is a conditional flattener - profits if curve flattens in a rally.
    """
    base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

    return pd.DataFrame([
        {
            "trade_id": "CF001",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 50_000_000,  # Smaller
            "strike": 3.50,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,
            "forward_start_years": 1.0,
            "premium": 100000.0,
        },
        {
            "trade_id": "CF002",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=10),
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,  # Larger (long)
            "strike": 3.75,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 30.0,  # 30Y tail
            "forward_start_years": 1.0,
            "premium": 200000.0,
        },
    ])


class TestConditionalCurveDetection:
    """Tests for conditional curve trade detection."""

    def test_conditional_steepener_detection(self, conditional_steepener_df, config):
        """Test detection of conditional steepener."""
        from SDRUtils.packages.swaption_packages import detect_swaption_conditional_curve_df

        result = detect_swaption_conditional_curve_df(
            conditional_steepener_df,
            time_window_seconds=120,
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 2

        # Should be labeled as CONDITIONAL_STEEPENER
        assert (packaged["package_type"] == "CONDITIONAL_STEEPENER").all()

        # Reason should contain tail info
        reason = packaged["package_reason"].iloc[0]
        assert "tails=" in reason
        assert "10" in reason and "30" in reason

    def test_conditional_flattener_detection(self, conditional_flattener_df, config):
        """Test detection of conditional flattener."""
        from SDRUtils.packages.swaption_packages import detect_swaption_conditional_curve_df

        result = detect_swaption_conditional_curve_df(
            conditional_flattener_df,
            time_window_seconds=120,
            config=config,
        )

        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 2

        # Should be labeled as CONDITIONAL_FLATTENER
        assert (packaged["package_type"] == "CONDITIONAL_FLATTENER").all()

    def test_conditional_curve_requires_same_expiry(self, config):
        """Test that different expiries don't form conditional curve."""
        base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

        df = pd.DataFrame([
            {
                "trade_id": "DE001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.00,
                "expiration_date": pd.Timestamp("2027-01-06"),  # 1Y expiry
                "tenor_years": 10.0,
                "forward_start_years": 1.0,
            },
            {
                "trade_id": "DE002",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 50_000_000,
                "strike": 4.25,
                "expiration_date": pd.Timestamp("2028-01-06"),  # Different expiry!
                "tenor_years": 30.0,
                "forward_start_years": 2.0,  # Different forward
            },
        ])

        from SDRUtils.packages.swaption_packages import detect_swaption_conditional_curve_df

        result = detect_swaption_conditional_curve_df(df, config=config)
        packaged = result[result["package_id"].notna()]

        # Should NOT detect (different expiries)
        assert len(packaged) == 0

    def test_conditional_curve_requires_min_tail_diff(self, config):
        """Test that small tail differences don't form conditional curve."""
        base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

        df = pd.DataFrame([
            {
                "trade_id": "MT001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.00,
                "expiration_date": pd.Timestamp("2027-01-06"),
                "tenor_years": 10.0,
                "forward_start_years": 1.0,
            },
            {
                "trade_id": "MT002",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "strike": 4.00,
                "expiration_date": pd.Timestamp("2027-01-06"),
                "tenor_years": 12.0,  # Only 2Y difference (< 5Y min)
                "forward_start_years": 1.0,
            },
        ])

        from SDRUtils.packages.swaption_packages import detect_swaption_conditional_curve_df

        result = detect_swaption_conditional_curve_df(df, config=config)
        packaged = result[result["package_id"].notna()]

        # Should NOT detect (tail diff too small)
        assert len(packaged) == 0


# =============================================================================
# Vega Curve Detection Tests
# =============================================================================


@pytest.fixture
def vega_expiry_spread_df():
    """
    Example vega expiry spread: 9Mx10Y vs 1Yx10Y straddles.

    From trader context: 9m1y vs 1y1y with similar vega.
    This trades the vol term structure.
    """
    base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

    return pd.DataFrame([
        # First straddle: 9Mx10Y
        {
            "trade_id": "VE001",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.00,
            "expiration_date": pd.Timestamp("2026-10-06"),
            "tenor_years": 10.0,
            "forward_start_years": 0.75,  # 9M expiry
            "premium": 48000.0,
        },
        {
            "trade_id": "VE002",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 4.00,
            "expiration_date": pd.Timestamp("2026-10-06"),
            "tenor_years": 10.0,
            "forward_start_years": 0.75,
            "premium": 48000.0,
        },
        # Second straddle: 1Yx10Y (different expiry, same tail)
        {
            "trade_id": "VE003",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=30),
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 3.95,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,  # Same tail
            "forward_start_years": 1.0,  # 1Y expiry (different)
            "premium": 52000.0,
        },
        {
            "trade_id": "VE004",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts + pd.Timedelta(seconds=30),
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 100_000_000,
            "strike": 3.95,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,
            "forward_start_years": 1.0,
            "premium": 52000.0,
        },
    ])


@pytest.fixture
def vega_tail_spread_df():
    """
    Example vega tail spread: 1Yx5Y vs 1Yx10Y straddles.

    This is the 4y5y vs 2y5y example from trader context.
    Trades the vol smile across the curve.
    """
    base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

    return pd.DataFrame([
        # First straddle: 1Yx5Y
        {
            "trade_id": "VT001",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 230_000_000,
            "strike": 4.025,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 5.0,  # 5Y tail
            "forward_start_years": 1.0,
            "premium": 125000.0,
        },
        {
            "trade_id": "VT002",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 230_000_000,
            "strike": 4.025,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 5.0,
            "forward_start_years": 1.0,
            "premium": 125000.0,
        },
        # Second straddle: 1Yx10Y (same expiry, different tail)
        {
            "trade_id": "VT003",
            "product_type": "SWAPTION_PAYER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 150_000_000,
            "strike": 3.981,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,  # 10Y tail (different)
            "forward_start_years": 1.0,  # Same expiry
            "premium": 135000.0,
        },
        {
            "trade_id": "VT004",
            "product_type": "SWAPTION_RECEIVER",
            "execution_timestamp": base_ts,
            "Platform identifier": "BILT",
            "notional_currency": "USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "notional": 150_000_000,
            "strike": 3.981,
            "expiration_date": pd.Timestamp("2027-01-06"),
            "tenor_years": 10.0,
            "forward_start_years": 1.0,
            "premium": 135000.0,
        },
    ])


class TestVegaCurveDetection:
    """Tests for vega curve trade detection."""

    def test_vega_expiry_spread_detection(self, vega_expiry_spread_df, config):
        """Test detection of vega expiry spread (same tail, different expiry)."""
        from SDRUtils.packages.swaption_packages import (
            detect_swaption_straddles_df,
            detect_swaption_vega_curve_df,
        )

        # First detect straddles
        result = detect_swaption_straddles_df(
            vega_expiry_spread_df,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            strike_tolerance=0.01,
            notional_tolerance_pct=0.05,
            config=config,
        )

        # Then detect vega curve
        result = detect_swaption_vega_curve_df(
            result,
            time_window_seconds=300,
            config=config,
        )

        # Check straddles were detected
        straddles = result[result["package_type"] == "STRADDLE"]
        assert len(straddles) == 4, "Should have 4 legs in 2 straddles"

        # Check vega curve was detected
        vega_curve = result[result["vega_curve_type"].notna()]
        assert len(vega_curve) > 0, "Should detect vega curve"

        # Should be VEGA_EXPIRY_SPREAD (same tail, different expiry)
        assert (vega_curve["vega_curve_type"] == "VEGA_EXPIRY_SPREAD").all()

    def test_vega_tail_spread_detection(self, vega_tail_spread_df, config):
        """Test detection of vega tail spread (same expiry, different tail)."""
        from SDRUtils.packages.swaption_packages import (
            detect_swaption_straddles_df,
            detect_swaption_vega_curve_df,
        )

        # First detect straddles
        result = detect_swaption_straddles_df(
            vega_tail_spread_df,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            strike_tolerance=0.05,
            notional_tolerance_pct=0.05,
            config=config,
        )

        # Then detect vega curve
        result = detect_swaption_vega_curve_df(
            result,
            time_window_seconds=300,
            config=config,
        )

        # Check straddles were detected
        straddles = result[result["package_type"] == "STRADDLE"]
        assert len(straddles) == 4

        # Check vega curve was detected
        vega_curve = result[result["vega_curve_type"].notna()]
        assert len(vega_curve) > 0

        # Should be VEGA_TAIL_SPREAD (same expiry, different tail)
        assert (vega_curve["vega_curve_type"] == "VEGA_TAIL_SPREAD").all()

    def test_vega_curve_requires_straddles(self, config):
        """Test that vega curve detection requires pre-detected straddles."""
        from SDRUtils.packages.swaption_packages import detect_swaption_vega_curve_df

        # DataFrame without any straddle annotations
        df = pd.DataFrame([
            {
                "trade_id": "NV001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": pd.Timestamp("2026-01-06 10:00:00", tz="UTC"),
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "notional": 100_000_000,
                "tenor_years": 10.0,
                "forward_start_years": 1.0,
                "premium": 50000.0,
                "package_type": "SWAPTION",
            },
        ])

        result = detect_swaption_vega_curve_df(df, config=config)

        # Should not detect anything (no straddles)
        vega_curve = result[result["vega_curve_type"].notna()]
        assert len(vega_curve) == 0


# =============================================================================
# Combined Detection Pipeline Tests
# =============================================================================


class TestCombinedDetectionPipeline:
    """Tests for the combined detection pipeline."""

    def test_full_pipeline_with_all_structures(self, config):
        """Test that full pipeline detects multiple structure types."""
        from SDRUtils.packages.swaption_packages import detect_and_link_swaption_packages_df

        base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

        # Create a diverse set of trades
        df = pd.DataFrame([
            # Straddle
            {
                "trade_id": "FP001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 100_000_000,
                "strike": 4.00,
                "expiration_date": pd.Timestamp("2027-01-06"),
                "tenor_years": 10.0,
                "forward_start_years": 1.0,
                "premium": 50000.0,
            },
            {
                "trade_id": "FP002",
                "product_type": "SWAPTION_RECEIVER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 100_000_000,
                "strike": 4.00,
                "expiration_date": pd.Timestamp("2027-01-06"),
                "tenor_years": 10.0,
                "forward_start_years": 1.0,
                "premium": 50000.0,
            },
            # 1x2 Vertical Spread (later in time)
            {
                "trade_id": "FP003",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts + pd.Timedelta(minutes=5),
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 100_000_000,
                "strike": 4.50,
                "expiration_date": pd.Timestamp("2027-06-06"),
                "tenor_years": 5.0,
                "forward_start_years": 0.5,
                "premium": 30000.0,
            },
            {
                "trade_id": "FP004",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts + pd.Timedelta(minutes=5, seconds=10),
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 200_000_000,  # 1x2
                "strike": 5.00,
                "expiration_date": pd.Timestamp("2027-06-06"),
                "tenor_years": 5.0,
                "forward_start_years": 0.5,
                "premium": 15000.0,
            },
        ])

        result = detect_and_link_swaption_packages_df(
            df,
            config=config,
            detect_straddles=True,
            detect_vertical_spreads=True,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            straddle_strike_tolerance=0.01,
            straddle_notional_tolerance_pct=0.05,
        )

        # Check straddle detected
        straddles = result[result["package_type"] == "STRADDLE"]
        assert len(straddles) == 2

        # Check vertical spread detected
        spreads = result[result["package_type"].str.startswith("VERTICAL_SPREAD", na=False)]
        assert len(spreads) == 2

    def test_detection_priority_order(self, config):
        """Test that detection follows priority order (risk reversals first)."""
        # This ensures trades matched by higher-priority detectors aren't
        # re-matched by lower-priority ones
        from SDRUtils.packages.swaption_packages import detect_and_link_swaption_packages_df

        # Would need IDB platform data with risk reversal structure
        # Simplified test: ensure straddles are detected before vertical spreads
        base_ts = pd.Timestamp("2026-01-06 10:00:00", tz="UTC")

        # Create trades that could be either straddle or vertical spread
        df = pd.DataFrame([
            {
                "trade_id": "PO001",
                "product_type": "SWAPTION_PAYER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 100_000_000,
                "strike": 4.00,
                "expiration_date": pd.Timestamp("2027-01-06"),
                "tenor_years": 10.0,
                "forward_start_years": 1.0,
                "premium": 50000.0,
            },
            {
                "trade_id": "PO002",
                "product_type": "SWAPTION_RECEIVER",
                "execution_timestamp": base_ts,
                "Platform identifier": "BILT",
                "notional_currency": "USD",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "notional": 100_000_000,
                "strike": 4.00,
                "expiration_date": pd.Timestamp("2027-01-06"),
                "tenor_years": 10.0,
                "forward_start_years": 1.0,
                "premium": 50000.0,
            },
        ])

        result = detect_and_link_swaption_packages_df(
            df,
            config=config,
            straddle_timestamp_tolerance=datetime.timedelta(seconds=60),
            straddle_strike_tolerance=0.01,
            straddle_notional_tolerance_pct=0.05,
        )

        # Should be detected as STRADDLE (higher priority), not vertical spread
        packaged = result[result["package_id"].notna()]
        assert len(packaged) == 2
        assert (packaged["package_type"] == "STRADDLE").all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
