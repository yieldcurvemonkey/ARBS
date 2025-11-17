# ABOUTME: Tests for EM FX carry signal (NEW CAPABILITY)
# ABOUTME: Validates interest rate differential carry trades for emerging market currencies

"""
Tests for EM FX Carry Signal

Tests FX carry strategy for emerging market currencies:
- Interest rate differential calculation
- Forward premium/discount pricing
- Carry-to-risk ratio (Sharpe-like metric)
- Cross-sectional ranking of FX carry
- Volatility adjustment

Carry Trade Logic:
- Borrow in low-yield currency (funding currency)
- Lend in high-yield currency (target currency)
- Profit = interest differential - FX depreciation
- Uncovered Interest Parity (UIP) violation drives alpha

Following TDD: These tests are written FIRST, then implementation.
"""

import pytest
import numpy as np
import polars as pl
from datetime import date, timedelta
from typing import Dict, List


class TestEMFXCarrySignal:
    """Test EM FX carry signal construction and basics."""

    def test_signal_import(self):
        """Test that EM FX carry signal can be imported."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal
        assert EMFXCarrySignal is not None

    def test_signal_creation(self):
        """Test creating an EM FX carry signal."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE & ACT
        signal = EMFXCarrySignal(
            funding_currency="USD",
            lookback_days=60,
            risk_adjust=True
        )

        # ASSERT
        assert signal.funding_currency == "USD"
        assert signal.lookback_days == 60
        assert signal.risk_adjust is True
        assert signal.name == "em_fx_carry"  # BaseSignal attribute

    def test_signal_extends_base_signal(self):
        """Test that EMFXCarrySignal properly extends BaseSignal."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal
        from Signals.Base.BaseSignal import BaseSignal

        # ARRANGE & ACT
        signal = EMFXCarrySignal()

        # ASSERT
        assert isinstance(signal, BaseSignal)
        assert hasattr(signal, 'generate')
        assert hasattr(signal, 'generate_batch')
        assert hasattr(signal, '_calculate_raw_signal')

    def test_interest_differential_calculation(self):
        """Test calculation of interest rate differential."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(funding_currency="USD")

        # BRL: 13.75% interest rate
        # USD: 5.50% interest rate
        # Carry = 13.75% - 5.50% = 8.25%

        # ACT
        carry = signal._calculate_interest_differential(
            target_rate=0.1375,
            funding_rate=0.0550
        )

        # ASSERT
        assert abs(carry - 0.0825) < 0.0001

    def test_forward_premium_calculation(self):
        """Test forward premium/discount calculation."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(funding_currency="USD")

        # Spot: 5.00 BRL/USD
        # 1Y Forward: 5.40 BRL/USD
        # Forward premium: (5.40 - 5.00) / 5.00 = 8%

        # ACT
        forward_premium = signal._calculate_forward_premium(
            spot_rate=5.00,
            forward_rate=5.40
        )

        # ASSERT
        assert abs(forward_premium - 0.08) < 0.001

    def test_carry_to_risk_ratio(self):
        """Test carry-to-risk (Sharpe-like) calculation."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(risk_adjust=True)

        # Carry: 8%
        # FX volatility: 16% (annualized)
        # Carry-to-risk: 8% / 16% = 0.50

        # ACT
        carry_to_risk = signal._calculate_carry_to_risk(
            carry=0.08,
            fx_volatility=0.16
        )

        # ASSERT
        assert abs(carry_to_risk - 0.50) < 0.01


class TestEMFXVolatilityAdjustment:
    """Test volatility adjustment for carry signals."""

    def test_volatility_calculation_from_returns(self):
        """Test FX volatility calculation from historical returns."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(lookback_days=60)

        # Create FX return series
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(60)]
        returns = np.random.randn(60) * 0.01  # 1% daily vol
        fx_history = pl.DataFrame({
            "date": dates,
            "fx_return": returns
        })

        # ACT
        vol = signal._calculate_fx_volatility(fx_history)

        # ASSERT: Annualized vol should be around 1% * sqrt(252) ≈ 16%
        assert isinstance(vol, float)
        assert vol > 0
        assert 0.10 < vol < 0.25  # Reasonable range

    def test_risk_adjusted_vs_unadjusted_carry(self):
        """Test that risk-adjusted carry differs from raw carry."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # High carry, high vol currency
        high_carry_high_vol = {
            "carry": 0.10,      # 10% carry
            "fx_vol": 0.20      # 20% vol
        }

        # Lower carry, low vol currency
        low_carry_low_vol = {
            "carry": 0.05,      # 5% carry
            "fx_vol": 0.10      # 10% vol
        }

        signal = EMFXCarrySignal(risk_adjust=True)

        # ACT
        adjusted_high = signal._calculate_carry_to_risk(
            high_carry_high_vol["carry"],
            high_carry_high_vol["fx_vol"]
        )
        adjusted_low = signal._calculate_carry_to_risk(
            low_carry_low_vol["carry"],
            low_carry_low_vol["fx_vol"]
        )

        # ASSERT
        # High: 10% / 20% = 0.50
        # Low: 5% / 10% = 0.50
        # Risk-adjusted should be equal!
        assert abs(adjusted_high - adjusted_low) < 0.01

        # But raw carry is different
        assert high_carry_high_vol["carry"] > low_carry_low_vol["carry"]


class TestEMFXCrossSecti onal:
    """Test cross-sectional EM FX carry ranking."""

    def test_cross_sectional_carry_ranking(self):
        """Test ranking EM currencies by carry."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(
            funding_currency="USD",
            normalization="rank",
            risk_adjust=False
        )

        # Create carry data for EM currencies
        em_carry_data = {
            "BRL": 0.0825,  # Brazil: 13.75% - 5.5% = 8.25%
            "TRY": 0.1950,  # Turkey: 25% - 5.5% = 19.5%
            "ZAR": 0.0300,  # South Africa: 8.5% - 5.5% = 3%
            "MXN": 0.0550,  # Mexico: 11% - 5.5% = 5.5%
        }

        # ACT
        normalized = signal._normalize_signals(em_carry_data)

        # ASSERT
        # Ranking: TRY > BRL > MXN > ZAR
        sorted_currencies = sorted(normalized.keys(), key=lambda k: normalized[k], reverse=True)
        assert sorted_currencies == ["TRY", "BRL", "MXN", "ZAR"]

        # Check range is [-1, 1]
        assert -1.0 <= min(normalized.values()) <= -0.9
        assert 0.9 <= max(normalized.values()) <= 1.0

    def test_multiple_currencies_evaluation(self):
        """Test evaluating carry across multiple EM currencies."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(
            funding_currency="USD",
            risk_adjust=True
        )

        # Mock currency data
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(60)]

        # Prepare currency data (list of DataFrames)
        brl_data = pl.DataFrame({
            "date": dates,
            "interest_rate": [0.1375] * 60,
            "fx_rate": [5.0 + np.random.randn() * 0.1 for _ in range(60)],
            "usd_rate": [0.055] * 60
        })

        try_data = pl.DataFrame({
            "date": dates,
            "interest_rate": [0.25] * 60,
            "fx_rate": [32.0 + np.random.randn() * 0.8 for _ in range(60)],
            "usd_rate": [0.055] * 60
        })

        mxn_data = pl.DataFrame({
            "date": dates,
            "interest_rate": [0.11] * 60,
            "fx_rate": [17.0 + np.random.randn() * 0.3 for _ in range(60)],
            "usd_rate": [0.055] * 60
        })

        currency_data_list = [brl_data, try_data, mxn_data]
        currency_labels = ["BRL", "TRY", "MXN"]

        # ACT
        # Use BaseSignal.generate_batch() to get z-scores
        z_scores = signal.generate_batch(
            inst_data_list=currency_data_list,
            market_data=None,
            as_of=dates[-1]
        )

        # ASSERT
        assert isinstance(z_scores, np.ndarray)
        assert len(z_scores) == 3

        # Z-scores should be standardized (approximately mean=0, std=1)
        assert abs(np.mean(z_scores)) < 0.5  # Approximately zero mean

        # TRY should have highest raw carry (highest z-score)
        # But after risk adjustment, ordering might change


class TestEMFXPortfolioConstruction:
    """Test portfolio construction from EM FX carry signals."""

    def test_long_short_fx_portfolio(self):
        """Test generating long/short FX portfolio from carry signals."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(
            funding_currency="USD",
            long_threshold=0.5,
            short_threshold=-0.5
        )

        carry_signals = {
            "BRL": 0.8,   # Strong carry - long
            "TRY": 1.2,   # Very strong carry - long
            "MXN": 0.2,   # Weak carry - neutral
            "ZAR": -0.7,  # Negative carry - short
        }

        # ACT
        weights = signal.generate_portfolio_weights(carry_signals)

        # ASSERT
        assert weights["BRL"] > 0  # Long
        assert weights["TRY"] > 0  # Long
        assert abs(weights["MXN"]) < 0.1  # Neutral
        assert weights["ZAR"] < 0  # Short

        # Dollar neutral (sum close to 0)
        assert abs(sum(weights.values())) < 0.1

    def test_carry_decay_over_time(self):
        """Test that carry decays as time passes (realized carry)."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(funding_currency="USD")

        # Initial carry: 10% annual
        # After 6 months: Should realize ~5%
        # After 1 year: Should realize ~10%

        initial_carry = 0.10
        days_held = 180  # 6 months

        # ACT
        realized_carry = signal._calculate_realized_carry(
            annual_carry=initial_carry,
            days_held=days_held
        )

        # ASSERT: Should be approximately 5% (half year)
        expected = initial_carry * (days_held / 365)
        assert abs(realized_carry - expected) < 0.001


class TestEMFXUIPViolation:
    """Test Uncovered Interest Parity (UIP) violation detection."""

    def test_uip_condition_check(self):
        """Test checking if UIP holds (it usually doesn't for EM)."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal()

        # UIP: Forward premium should equal interest differential
        # If violated: Carry trade opportunity exists

        interest_diff = 0.08  # 8% carry
        forward_premium = 0.04  # Forward implies only 4% depreciation

        # ACT
        uip_violation = signal._check_uip_violation(
            interest_differential=interest_diff,
            forward_premium=forward_premium
        )

        # ASSERT
        # UIP violated: Expected 8% depreciation, forward shows 4%
        # Violation = 8% - 4% = 4% alpha opportunity
        assert abs(uip_violation - 0.04) < 0.001

    def test_uip_holds_no_opportunity(self):
        """Test when UIP holds (no carry opportunity)."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal()

        # Perfect UIP: Forward = Interest differential
        interest_diff = 0.08
        forward_premium = 0.08

        # ACT
        uip_violation = signal._check_uip_violation(
            interest_differential=interest_diff,
            forward_premium=forward_premium
        )

        # ASSERT
        assert abs(uip_violation) < 0.001  # No violation


class TestEMFXEdgeCases:
    """Test edge cases and error handling."""

    def test_negative_carry_short_position(self):
        """Test handling of negative carry (short high-yield currency)."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(funding_currency="USD")

        # Target currency has LOWER rate than funding
        # Carry is negative
        carry = signal._calculate_interest_differential(
            target_rate=0.03,   # 3%
            funding_rate=0.055  # 5.5%
        )

        # ASSERT
        assert carry < 0

    def test_infinite_volatility_handling(self):
        """Test handling of zero or infinite volatility."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(risk_adjust=True)

        # ACT: Zero volatility should return 0 or handle gracefully
        result = signal._calculate_carry_to_risk(
            carry=0.08,
            fx_volatility=0.0
        )

        # ASSERT: Should handle gracefully (return 0 or cap)
        assert isinstance(result, float)
        assert not np.isinf(result)
        assert not np.isnan(result)

    def test_insufficient_fx_history(self):
        """Test handling of insufficient FX history for volatility."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(lookback_days=60)

        # Only 10 days of data
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(10)]
        fx_history = pl.DataFrame({
            "date": dates,
            "fx_return": np.random.randn(10) * 0.01
        })

        # ACT & ASSERT
        with pytest.raises(ValueError, match="Insufficient|data"):
            signal._calculate_fx_volatility(fx_history)


class TestEMFXIntegration:
    """Integration tests for EM FX carry strategy."""

    def test_full_carry_trade_workflow(self):
        """Test complete workflow: data -> signal -> weights."""
        from Signals.EMFXCarrySignal import EMFXCarrySignal

        # ARRANGE
        signal = EMFXCarrySignal(
            funding_currency="USD",
            risk_adjust=True,
            normalization="z_score"
        )

        # Create realistic EM currency data
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(90)]

        currency_data = {
            "BRL": {
                "interest_rate": 0.1375,
                "fx_history": [5.0 * (1 + np.random.randn() * 0.02) for _ in range(90)],
            },
            "MXN": {
                "interest_rate": 0.11,
                "fx_history": [17.0 * (1 + np.random.randn() * 0.015) for _ in range(90)],
            },
            "ZAR": {
                "interest_rate": 0.085,
                "fx_history": [18.5 * (1 + np.random.randn() * 0.025) for _ in range(90)],
            }
        }

        usd_rate = 0.055

        # ACT: Calculate carry signals
        # (This will be implemented - test defines interface)

        # ASSERT: Should return dict of z-scored signals
        # Format verified in implementation
        pass  # Placeholder - full implementation will be tested
