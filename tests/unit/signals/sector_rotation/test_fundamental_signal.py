"""
Test suite for FundamentalSignal.

Tests the neural network signal for fundamental-based sector prediction.
TDD approach: tests written BEFORE implementation.
"""

from datetime import date
import numpy as np
import polars as pl


class TestFundamentalSignal:
    """Test FundamentalSignal neural network integration with BaseSignal."""

    def test_signal_initialization(self):
        """Test signal initializes with correct neural network architecture."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal()

        # Check BaseSignal attributes
        assert signal.name == "sector_fundamental"
        assert signal.standardize is True

        # Check neural network configuration (paper specs)
        assert signal.hidden_layers == (5, 5)  # Two layers, 5 nodes each
        assert signal.alpha == 0.5  # L2 regularization
        assert signal.is_trained is False  # Not trained yet

    def test_signal_custom_parameters(self):
        """Test signal initialization with custom neural network config."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal(
            hidden_layers=(10, 10),
            alpha=1.0,
            standardize=False
        )

        assert signal.hidden_layers == (10, 10)
        assert signal.alpha == 1.0
        assert signal.standardize is False

    def test_train_neural_network(self):
        """Test neural network can be trained with fundamental data."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal(hidden_layers=(5, 5), alpha=0.5)

        # Create training data (simplified - 11 features per observation)
        # Features: PE, PB, EV/Sales, EV/EBIT, EV/EBITDA, Div Yield, GM, OM, PM, ROA, ROE
        X_train = np.array([
            [0.5, 0.3, 0.2, 0.1, -0.1, 0.0, 0.6, 0.4, 0.3, 0.2, 0.5],  # High quality
            [-0.5, -0.3, -0.2, -0.1, 0.1, 0.0, -0.6, -0.4, -0.3, -0.2, -0.5],  # Low quality
            [0.3, 0.2, 0.1, 0.0, -0.2, 0.1, 0.4, 0.3, 0.2, 0.1, 0.3],  # Medium quality
            [-0.3, -0.2, -0.1, 0.0, 0.2, -0.1, -0.4, -0.3, -0.2, -0.1, -0.3],  # Medium-low
        ] * 10)  # Repeat for 40 samples (minimum training size)

        # Labels: 1 = positive return, 0 = negative return
        y_train = np.array([1, 0, 1, 0] * 10)

        # Train
        signal.train(X_train, y_train)

        # Check training completed
        assert signal.is_trained is True
        assert signal.model is not None

    def test_predict_probabilities(self):
        """Test neural network returns probabilities [0, 1]."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal(hidden_layers=(5, 5))

        # Train with simple data
        X_train = np.array([
            [1.0] * 11,  # High values → positive
            [-1.0] * 11,  # Low values → negative
        ] * 20)
        y_train = np.array([1, 0] * 20)

        signal.train(X_train, y_train)

        # Predict on new data
        X_test = np.array([
            [0.8] * 11,  # Should predict positive (high)
            [-0.8] * 11,  # Should predict negative (low)
        ])

        probabilities = signal.predict_proba(X_test)

        # Check probabilities are in [0, 1]
        assert len(probabilities) == 2
        assert all(0 <= p <= 1 for p in probabilities)

        # High values should have higher probability
        assert probabilities[0] > 0.5  # Positive prediction
        assert probabilities[1] < 0.5  # Negative prediction

    def test_calculate_raw_signal_single_sector(self):
        """Test _calculate_raw_signal returns probability for single sector."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal()

        # Train model first
        X_train = np.array([[0.5] * 11, [-0.5] * 11] * 20)
        y_train = np.array([1, 0] * 20)
        signal.train(X_train, y_train)

        # Create inst_data with 11 neutralized fundamental factors
        inst_data = pl.DataFrame({
            "ticker": ["XLK"],
            "date": [date(2023, 3, 31)],
            "pe_ratio_neutral": [0.8],
            "pb_ratio_neutral": [0.6],
            "ev_sales_neutral": [0.5],
            "ev_ebit_neutral": [0.4],
            "ev_ebitda_neutral": [0.3],
            "dividend_yield_neutral": [0.2],
            "gross_margin_neutral": [0.7],
            "operating_margin_neutral": [0.6],
            "profit_margin_neutral": [0.5],
            "roa_neutral": [0.4],
            "roe_neutral": [0.8],
        })

        # Calculate raw signal (probability)
        prob = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=date(2023, 3, 31)
        )

        # Should return probability [0, 1]
        assert 0 <= prob <= 1
        # High quality factors should predict positive (> 0.5)
        assert prob > 0.5

    def test_generate_batch_multiple_sectors(self):
        """Test generate_batch for multiple sectors without standardization."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal(standardize=False)

        # Train model
        X_train = np.array([[0.5] * 11, [-0.5] * 11] * 20)
        y_train = np.array([1, 0] * 20)
        signal.train(X_train, y_train)

        # Create data for 3 sectors with different quality
        target_date = date(2023, 3, 31)

        # High quality sector
        xlk_data = pl.DataFrame({
            "ticker": ["XLK"],
            "date": [target_date],
            **{f"{col}_neutral": [0.7] for col in [
                "pe_ratio", "pb_ratio", "ev_sales", "ev_ebit", "ev_ebitda",
                "dividend_yield", "gross_margin", "operating_margin",
                "profit_margin", "roa", "roe"
            ]}
        })

        # Medium quality sector
        xlf_data = pl.DataFrame({
            "ticker": ["XLF"],
            "date": [target_date],
            **{f"{col}_neutral": [0.0] for col in [
                "pe_ratio", "pb_ratio", "ev_sales", "ev_ebit", "ev_ebitda",
                "dividend_yield", "gross_margin", "operating_margin",
                "profit_margin", "roa", "roe"
            ]}
        })

        # Low quality sector
        xle_data = pl.DataFrame({
            "ticker": ["XLE"],
            "date": [target_date],
            **{f"{col}_neutral": [-0.7] for col in [
                "pe_ratio", "pb_ratio", "ev_sales", "ev_ebit", "ev_ebitda",
                "dividend_yield", "gross_margin", "operating_margin",
                "profit_margin", "roa", "roe"
            ]}
        })

        # Generate batch signals
        probabilities = signal.generate_batch(
            inst_data_list=[xlk_data, xlf_data, xle_data],
            market_data=None,
            as_of=target_date
        )

        # Check probabilities
        assert len(probabilities) == 3
        assert all(0 <= p <= 1 for p in probabilities)

        # Quality ranking should be preserved
        assert probabilities[0] > probabilities[1] > probabilities[2]  # XLK > XLF > XLE

    def test_generate_batch_with_standardization(self):
        """Test generate_batch applies z-score standardization to probabilities."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal(standardize=True)

        # Train model
        X_train = np.array([[0.5] * 11, [-0.5] * 11] * 20)
        y_train = np.array([1, 0] * 20)
        signal.train(X_train, y_train)

        # Create data for 3 sectors
        target_date = date(2023, 3, 31)
        inst_data_list = []

        for ticker, quality in [("XLK", 0.7), ("XLF", 0.0), ("XLE", -0.7)]:
            inst_data_list.append(pl.DataFrame({
                "ticker": [ticker],
                "date": [target_date],
                **{f"{col}_neutral": [quality] for col in [
                    "pe_ratio", "pb_ratio", "ev_sales", "ev_ebit", "ev_ebitda",
                    "dividend_yield", "gross_margin", "operating_margin",
                    "profit_margin", "roa", "roe"
                ]}
            }))

        # Generate with standardization
        z_scores = signal.generate_batch(
            inst_data_list=inst_data_list,
            market_data=None,
            as_of=target_date
        )

        # Check z-score properties
        assert len(z_scores) == 3
        assert abs(np.mean(z_scores)) < 1e-6  # Mean ≈ 0
        assert abs(np.std(z_scores, ddof=1) - 1.0) < 1e-6  # Std ≈ 1

    def test_untrained_model_raises_error(self):
        """Test that untrained model raises error on prediction."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal()

        inst_data = pl.DataFrame({
            "ticker": ["XLK"],
            "date": [date(2023, 3, 31)],
            **{f"{col}_neutral": [0.5] for col in [
                "pe_ratio", "pb_ratio", "ev_sales", "ev_ebit", "ev_ebitda",
                "dividend_yield", "gross_margin", "operating_margin",
                "profit_margin", "roa", "roe"
            ]}
        })

        try:
            signal._calculate_raw_signal(inst_data, None, date(2023, 3, 31))
            raise AssertionError("Expected ValueError for untrained model")
        except ValueError as e:
            assert "not been trained" in str(e).lower()

    def test_neural_network_architecture(self):
        """Test that neural network has correct architecture from paper."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal()

        # Train to instantiate model
        X_train = np.array([[0.5] * 11, [-0.5] * 11] * 20)
        y_train = np.array([1, 0] * 20)
        signal.train(X_train, y_train)

        # Check architecture
        model = signal.model
        assert hasattr(model, 'hidden_layer_sizes')
        assert model.hidden_layer_sizes == (5, 5)  # Paper's configuration

    def test_l2_regularization(self):
        """Test that L2 regularization is applied (alpha parameter)."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal(alpha=0.5)

        # Train
        X_train = np.array([[0.5] * 11, [-0.5] * 11] * 20)
        y_train = np.array([1, 0] * 20)
        signal.train(X_train, y_train)

        # Check L2 regularization parameter
        assert signal.model.alpha == 0.5

    def test_binary_classification_output(self):
        """Test that model outputs binary classification (2 classes)."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal()

        # Train
        X_train = np.array([[0.5] * 11, [-0.5] * 11] * 20)
        y_train = np.array([1, 0] * 20)
        signal.train(X_train, y_train)

        # Check classes
        assert len(signal.model.classes_) == 2
        assert set(signal.model.classes_) == {0, 1}

    def test_feature_validation(self):
        """Test that exactly 11 features are required (paper specification)."""
        from Signals.SectorRotation.FundamentalSignal import FundamentalSignal

        signal = FundamentalSignal()

        # Expected 11 neutralized factor columns
        expected_features = [
            "pe_ratio_neutral", "pb_ratio_neutral", "ev_sales_neutral",
            "ev_ebit_neutral", "ev_ebitda_neutral", "dividend_yield_neutral",
            "gross_margin_neutral", "operating_margin_neutral",
            "profit_margin_neutral", "roa_neutral", "roe_neutral"
        ]

        assert signal.feature_columns == expected_features
        assert len(signal.feature_columns) == 11


if __name__ == "__main__":
    # Run tests
    test = TestFundamentalSignal()

    print("Running FundamentalSignal tests...")

    test.test_signal_initialization()
    print("✓ test_signal_initialization")

    test.test_signal_custom_parameters()
    print("✓ test_signal_custom_parameters")

    test.test_train_neural_network()
    print("✓ test_train_neural_network")

    test.test_predict_probabilities()
    print("✓ test_predict_probabilities")

    test.test_calculate_raw_signal_single_sector()
    print("✓ test_calculate_raw_signal_single_sector")

    test.test_generate_batch_multiple_sectors()
    print("✓ test_generate_batch_multiple_sectors")

    test.test_generate_batch_with_standardization()
    print("✓ test_generate_batch_with_standardization")

    test.test_untrained_model_raises_error()
    print("✓ test_untrained_model_raises_error")

    test.test_neural_network_architecture()
    print("✓ test_neural_network_architecture")

    test.test_l2_regularization()
    print("✓ test_l2_regularization")

    test.test_binary_classification_output()
    print("✓ test_binary_classification_output")

    test.test_feature_validation()
    print("✓ test_feature_validation")

    print("\n✅ All FundamentalSignal tests passed!")
