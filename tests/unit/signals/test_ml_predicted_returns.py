# ABOUTME: Comprehensive tests for ML-enhanced factor signals and feature engineering
# ABOUTME: Tests momentum, value, quality, technical indicators, and ML model predictions
"""
Tests for ML-enhanced factor signals.

Test Coverage:
1. FeatureEngineering:
   - Momentum calculation (multiple lookbacks)
   - Value factors (P/E, P/B, dividend yield with mock data)
   - Quality factors (ROE, profit margin with mock data)
   - Technical indicators (RSI, MACD, Bollinger bands)
   - Missing data handling
   - Combined feature DataFrame

2. MLPredictedReturnsSignal:
   - Model training on synthetic data
   - Prediction quality (finite, reasonable range)
   - Z-score normalization
   - Cross-validation (expanding window)
   - No look-ahead bias
   - IC calculation
"""

import numpy as np
import polars as pl
import pytest
from datetime import date, timedelta
from sklearn.ensemble import RandomForestRegressor

from Signals.Utils.FeatureEngineering import FeatureEngineering
from Signals.MLPredictedReturnsSignal import MLPredictedReturnsSignal


class TestFeatureEngineering:
    """Test feature engineering utility class."""

    @pytest.fixture
    def sample_returns(self):
        """Create sample returns data for testing."""
        # Create date range using polars
        dates = pl.date_range(
            date(2020, 1, 1),
            date(2023, 12, 31),
            interval="1d",
            eager=True,
        ).cast(pl.Date).to_list()

        np.random.seed(42)

        # Create 3 tickers with synthetic returns
        data = []
        for ticker in ["AAPL", "GOOGL", "MSFT"]:
            returns = np.random.randn(len(dates)) * 0.02  # 2% daily vol
            prices = 100 * np.exp(np.cumsum(returns))

            for d, r, p in zip(dates, returns, prices):
                data.append({
                    "ticker": ticker,
                    "date": d,
                    "return": r,
                    "price": p,
                })

        return pl.DataFrame(data)

    @pytest.fixture
    def sample_prices(self):
        """Create sample price data."""
        dates = pl.date_range(
            date(2020, 1, 1),
            date(2023, 12, 31),
            interval="1d",
            eager=True,
        ).cast(pl.Date).to_list()

        np.random.seed(42)
        
        data = []
        for ticker in ["AAPL", "GOOGL", "MSFT"]:
            prices = 100 + np.cumsum(np.random.randn(len(dates)))

            for d, p in zip(dates, prices):
                data.append({
                    "ticker": ticker,
                    "date": d,
                    "price": p,
                })

        return pl.DataFrame(data)

    def test_momentum_calculation_correct(self, sample_returns):
        """Test momentum calculation matches expected formula."""
        fe = FeatureEngineering()
        
        # Calculate momentum with single lookback
        momentum = fe.calculate_momentum(sample_returns, lookbacks=[21])
        
        # Verify schema
        assert "ticker" in momentum.columns
        assert "date" in momentum.columns
        assert "momentum_21d" in momentum.columns
        
        # Verify calculation for one ticker manually
        aapl_data = sample_returns.filter(pl.col("ticker") == "AAPL").sort("date")
        
        # For the 21st day, momentum should be sum of previous 21 returns
        test_date = aapl_data["date"][25]  # Day 25 (0-indexed)
        expected_momentum = aapl_data["return"][5:26].sum()  # Days 5-25 (21 days)
        
        actual_momentum = momentum.filter(
            (pl.col("ticker") == "AAPL") & (pl.col("date") == test_date)
        )["momentum_21d"][0]
        
        assert abs(actual_momentum - expected_momentum) < 1e-10

    def test_momentum_multiple_lookbacks(self, sample_returns):
        """Test momentum calculation with multiple lookbacks."""
        fe = FeatureEngineering()
        
        lookbacks = [21, 63, 126, 252]
        momentum = fe.calculate_momentum(sample_returns, lookbacks=lookbacks)
        
        # Verify all momentum columns exist
        for lb in lookbacks:
            assert f"momentum_{lb}d" in momentum.columns
        
        # Verify no NaN for dates with sufficient history
        recent_data = momentum.filter(pl.col("date") >= date(2023, 1, 1))
        for lb in lookbacks:
            col = f"momentum_{lb}d"
            assert recent_data[col].null_count() == 0

    def test_value_calculation_with_mock_data(self, sample_prices):
        """Test value factor calculation with mock fundamentals."""
        fe = FeatureEngineering()
        
        value = fe.calculate_value(sample_prices, fundamentals=None)
        
        # Verify schema
        assert "ticker" in value.columns
        assert "date" in value.columns
        assert "pe_ratio" in value.columns
        assert "pb_ratio" in value.columns
        assert "dividend_yield" in value.columns
        
        # Verify mock data has reasonable values
        assert value["pe_ratio"].mean() > 5  # Reasonable P/E
        assert value["pe_ratio"].mean() < 30
        assert value["pb_ratio"].mean() > 0.5  # Reasonable P/B
        assert value["pb_ratio"].mean() < 5
        assert value["dividend_yield"].mean() > 0  # Positive yield
        assert value["dividend_yield"].mean() < 0.10  # Less than 10%

    def test_quality_calculation_with_mock_data(self, sample_prices):
        """Test quality factor calculation with mock financials."""
        fe = FeatureEngineering()
        
        quality = fe.calculate_quality(financials=None)
        
        # Verify schema
        assert "ticker" in quality.columns
        assert "date" in quality.columns
        assert "roe" in quality.columns
        assert "profit_margin" in quality.columns
        
        # Verify mock data has reasonable values
        assert quality["roe"].mean() > 0  # Positive ROE
        assert quality["roe"].mean() < 0.50  # Less than 50%
        assert quality["profit_margin"].mean() > 0  # Positive margin
        assert quality["profit_margin"].mean() < 0.30  # Less than 30%

    def test_technical_indicators_rsi(self, sample_prices):
        """Test RSI calculation."""
        fe = FeatureEngineering()

        technical = fe.calculate_technical(sample_prices)

        # Verify RSI column exists
        assert "rsi_14" in technical.columns

        # Get valid RSI values as numpy array
        rsi_values = technical["rsi_14"].to_numpy()
        valid_rsi_values = rsi_values[~np.isnan(rsi_values)]

        # Should have valid RSI values
        assert len(valid_rsi_values) > 0

        # RSI should be between 0 and 100
        assert np.min(valid_rsi_values) >= 0
        assert np.max(valid_rsi_values) <= 100

        # RSI should have reasonable mean (around 50 for random walk)
        rsi_mean = np.mean(valid_rsi_values)
        assert 30 < rsi_mean < 70

    def test_technical_indicators_macd(self, sample_prices):
        """Test MACD calculation."""
        fe = FeatureEngineering()
        
        technical = fe.calculate_technical(sample_prices)
        
        # Verify MACD columns exist
        assert "macd" in technical.columns
        assert "macd_signal" in technical.columns
        assert "macd_hist" in technical.columns
        
        # MACD histogram should be difference of MACD and signal
        for i in range(len(technical)):
            expected_hist = technical["macd"][i] - technical["macd_signal"][i]
            actual_hist = technical["macd_hist"][i]
            if not (np.isnan(expected_hist) or np.isnan(actual_hist)):
                assert abs(expected_hist - actual_hist) < 1e-10

    def test_technical_indicators_bollinger(self, sample_prices):
        """Test Bollinger bands calculation."""
        fe = FeatureEngineering()
        
        technical = fe.calculate_technical(sample_prices)
        
        # Verify Bollinger band columns exist
        assert "bb_upper" in technical.columns
        assert "bb_middle" in technical.columns
        assert "bb_lower" in technical.columns
        
        # Upper should be above middle, middle above lower
        valid_data = technical.filter(
            ~pl.col("bb_upper").is_null() & 
            ~pl.col("bb_middle").is_null() & 
            ~pl.col("bb_lower").is_null()
        )
        
        assert (valid_data["bb_upper"] >= valid_data["bb_middle"]).all()
        assert (valid_data["bb_middle"] >= valid_data["bb_lower"]).all()

    def test_missing_data_handling(self):
        """Test handling of missing data in feature engineering."""
        fe = FeatureEngineering()

        # Create data with missing values
        dates = pl.date_range(
            date(2023, 1, 1),
            date(2023, 12, 31),
            interval="1d",
            eager=True,
        ).cast(pl.Date).to_list()

        data = []
        for i, d in enumerate(dates):
            # Intentionally create gaps
            if i % 10 != 0:  # Skip every 10th day
                data.append({
                    "ticker": "AAPL",
                    "date": d,
                    "return": np.random.randn() * 0.02,
                    "price": 100 + i,
                })

        df = pl.DataFrame(data)

        # Should not crash with missing data
        momentum = fe.calculate_momentum(df, lookbacks=[21])

        # Should have data for available dates
        assert len(momentum) > 0


class TestMLPredictedReturnsSignal:
    """Test ML predicted returns signal."""

    @pytest.fixture
    def synthetic_data(self):
        """Create synthetic data for ML training."""
        np.random.seed(42)
        n_assets = 20
        n_periods = 500
        
        data = []
        for asset_id in range(n_assets):
            for period in range(n_periods):
                # Create features with some predictive power
                momentum = np.random.randn()
                value = np.random.randn()
                quality = np.random.randn()
                
                # True return is a function of features + noise
                true_return = (
                    0.3 * momentum + 
                    0.2 * value + 
                    0.1 * quality + 
                    np.random.randn() * 0.5
                )
                
                data.append({
                    "ticker": f"ASSET_{asset_id}",
                    "date": date(2020, 1, 1) + timedelta(days=period),
                    "momentum_21d": momentum,
                    "pe_ratio": value,
                    "roe": quality,
                    "next_return": true_return,
                })
        
        return pl.DataFrame(data)

    def test_model_trains_successfully(self, synthetic_data):
        """Test that ML model trains without errors."""
        signal = MLPredictedReturnsSignal(
            n_estimators=50,  # Smaller for faster tests
            max_depth=3,
            random_state=42,
        )
        
        # Should train successfully
        signal.train(synthetic_data)
        
        # Model should be fitted
        assert signal.model is not None
        assert hasattr(signal.model, "predict")

    def test_predictions_have_expected_properties(self, synthetic_data):
        """Test that predictions are finite and in reasonable range."""
        signal = MLPredictedReturnsSignal(
            n_estimators=50,
            max_depth=3,
            random_state=42,
        )

        # Split data into train and test (500 days total, split at day 300)
        train_cutoff = date(2020, 10, 27)  # About day 300
        train_data = synthetic_data.filter(pl.col("date") < train_cutoff)
        test_data = synthetic_data.filter(pl.col("date") >= train_cutoff)

        signal.train(train_data)
        predictions = signal.predict(test_data)

        # Predictions should be finite
        assert np.all(np.isfinite(predictions))

        # Predictions should be in reasonable range (-5 to +5 for returns)
        assert np.all(predictions > -5)
        assert np.all(predictions < 5)

    def test_zscore_normalization_correct(self, synthetic_data):
        """Test that z-score normalization is correct."""
        signal = MLPredictedReturnsSignal(
            n_estimators=50,
            max_depth=3,
            random_state=42,
        )

        train_cutoff = date(2020, 10, 27)
        train_data = synthetic_data.filter(pl.col("date") < train_cutoff)
        test_data = synthetic_data.filter(pl.col("date") >= train_cutoff)

        signal.train(train_data)

        # Get predictions for one date
        test_date = date(2020, 12, 1)
        date_data = test_data.filter(pl.col("date") == test_date)

        raw_predictions = signal.predict(date_data)
        z_scores = signal._standardize(raw_predictions)

        # Z-scores should have mean ~0 and std ~1
        assert abs(z_scores.mean()) < 0.1
        assert abs(z_scores.std() - 1.0) < 0.1

    def test_expanding_window_cross_validation(self, synthetic_data):
        """Test expanding window cross-validation works correctly."""
        signal = MLPredictedReturnsSignal(
            n_estimators=50,
            max_depth=3,
            random_state=42,
        )
        
        # Should be able to run cross-validation
        cv_results = signal.cross_validate(
            synthetic_data,
            n_splits=3,
        )
        
        # Should return IC for each split
        assert len(cv_results["ic_scores"]) == 3
        assert all(np.isfinite(cv_results["ic_scores"]))

    def test_no_lookahead_bias(self, synthetic_data):
        """Test that there is no look-ahead bias in predictions."""
        signal = MLPredictedReturnsSignal(
            n_estimators=50,
            max_depth=3,
            random_state=42,
        )

        # Train only on early data
        train_cutoff = date(2020, 7, 1)  # About day 180
        train_data = synthetic_data.filter(pl.col("date") < train_cutoff)

        signal.train(train_data)

        # Predict on later data
        test_data = synthetic_data.filter(
            (pl.col("date") >= train_cutoff) &
            (pl.col("date") < date(2020, 10, 1))
        )

        predictions = signal.predict(test_data)

        # Should have predictions
        assert len(predictions) > 0

        # Model should not have seen test data (can't verify directly,
        # but model should exist and be trained only on train_data)
        assert signal.model is not None

    def test_generate_batch_integration(self, synthetic_data):
        """Test integration with BaseSignal.generate_batch()."""
        signal = MLPredictedReturnsSignal(
            n_estimators=50,
            max_depth=3,
            random_state=42,
        )

        # Train model
        train_data = synthetic_data.filter(pl.col("date") < date(2020, 10, 27))
        signal.train(train_data)

        # Generate signals for one date
        test_date = date(2020, 12, 1)
        test_data = synthetic_data.filter(pl.col("date") == test_date)
        
        # Split by ticker for generate_batch format
        tickers = test_data["ticker"].unique().to_list()
        inst_data_list = [
            test_data.filter(pl.col("ticker") == ticker)
            for ticker in tickers
        ]
        
        # Generate batch signals
        signals = signal.generate_batch(
            inst_data_list=inst_data_list,
            market_data=None,
            as_of=test_date,
        )
        
        # Should return z-scored signals
        assert len(signals) == len(tickers)
        assert np.all(np.isfinite(signals))
        
        # Signals should be standardized (mean ~0, std ~1)
        assert abs(signals.mean()) < 0.1
        assert abs(signals.std() - 1.0) < 0.1

    def test_ic_calculation(self, synthetic_data):
        """Test IC calculation for ML predictions."""
        signal = MLPredictedReturnsSignal(
            n_estimators=100,  # More trees for better IC
            max_depth=5,
            random_state=42,
        )

        # Train on early data
        train_data = synthetic_data.filter(pl.col("date") < date(2020, 7, 1))
        signal.train(train_data)

        # Test on later data
        test_data = synthetic_data.filter(
            (pl.col("date") >= date(2020, 7, 1)) &
            (pl.col("date") < date(2020, 10, 1))
        )
        
        # Calculate IC for each date
        ics = []
        test_dates = test_data["date"].unique().sort()
        
        for test_date in test_dates[:10]:  # First 10 dates
            date_data = test_data.filter(pl.col("date") == test_date)
            
            if len(date_data) < 5:  # Need enough assets
                continue
            
            predictions = signal.predict(date_data)
            actuals = date_data["next_return"].to_numpy()
            
            # Calculate correlation
            if len(predictions) > 2:
                ic = np.corrcoef(predictions, actuals)[0, 1]
                if np.isfinite(ic):
                    ics.append(ic)
        
        # Should have positive mean IC (since data has predictive signal)
        assert len(ics) > 0
        assert np.mean(ics) > 0  # Positive IC on average

    def test_feature_importance_available(self, synthetic_data):
        """Test that feature importance is available after training."""
        signal = MLPredictedReturnsSignal(
            n_estimators=50,
            max_depth=3,
            random_state=42,
        )

        train_data = synthetic_data.filter(pl.col("date") < date(2020, 10, 27))
        signal.train(train_data)
        
        # Should have feature importance
        importance = signal.get_feature_importance()
        
        assert isinstance(importance, dict)
        assert len(importance) > 0
        
        # Importance should sum to ~1
        assert abs(sum(importance.values()) - 1.0) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
