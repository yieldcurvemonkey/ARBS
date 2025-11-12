# ABOUTME: Neural network signal for sector rotation using fundamental factors
# ABOUTME: Implements 2-layer MLP for binary classification (Yang & Shi 2023)
"""
FundamentalSignal - Neural network predictor for sector returns.

Uses 11 neutralized fundamental factors to predict probability of positive
next-quarter return via 2-layer neural network.

Neural Network Architecture (Yang & Shi 2023):
- Input: 11 fundamental factors (neutralized)
- Hidden Layer 1: 5 nodes, ReLU activation
- Hidden Layer 2: 5 nodes, ReLU activation
- Output: 2 nodes (binary classification), Softmax → probability [0, 1]
- Regularization: L2 penalty (alpha=0.5)
- Solver: Quasi-Newton methods (good for small samples)

Features (All Cross-Sectionally Neutralized):
1. PE Ratio, 2. PB Ratio, 3. EV/Sales, 4. EV/EBIT, 5. EV/EBITDA
6. Dividend Yield, 7. Gross Margin, 8. Operating Margin, 9. Profit Margin
10. ROA, 11. ROE

Training:
- Target: Binary (1=positive return, 0=negative return)
- Data split: 60% train, 20% validation, 20% test
- No shuffling (preserves temporal structure)

Performance (Paper):
- Test accuracy: 64%
- Sharpe ratio: 2.21 (combined with momentum/reversion)

Integration with Grinold-Kahn:
- Raw signal = predicted probability [0, 1]
- Cross-sectional standardization via BaseSignal (optional)
- IC tracking for alpha quality monitoring
- Scaled by AlphaGenerator: α = IC × Vol × Z

Example:
    >>> from sklearn.model_selection import train_test_split
    >>>
    >>> # Prepare training data (neutralized fundamentals + returns)
    >>> X = fundamental_df[signal.feature_columns].to_numpy()
    >>> y = (next_quarter_returns > 0).astype(int).to_numpy()
    >>>
    >>> # Train neural network
    >>> signal = FundamentalSignal(hidden_layers=(5, 5), alpha=0.5)
    >>> signal.train(X, y)
    >>>
    >>> # Generate signals for all sectors
    >>> sector_data_list = [xlk_fundamental, xle_fundamental, ...]
    >>> probabilities = signal.generate_batch(
    ...     inst_data_list=sector_data_list,
    ...     market_data=None,
    ...     as_of=date(2023, 12, 31)
    ... )
    >>> # probabilities[i] = P(positive return | fundamentals_i)
"""

from datetime import date
from typing import Optional, Tuple
import numpy as np
import polars as pl

from Signals.Base.BaseSignal import BaseSignal


class FundamentalSignal(BaseSignal):
    """
    Neural network signal for sector rotation using fundamental factors.

    Trains 2-layer MLP to predict probability of positive next-quarter return
    based on 11 neutralized fundamental factors.

    Attributes:
        hidden_layers: Tuple of hidden layer sizes (default: (5, 5))
        alpha: L2 regularization parameter (default: 0.5)
        feature_columns: List of 11 neutralized factor column names
        model: Trained MLPClassifier instance (None until trained)
        is_trained: Whether model has been trained
    """

    def __init__(
        self,
        hidden_layers: Tuple[int, ...] = (5, 5),
        alpha: float = 0.5,
        max_iter: int = 500,
        standardize: bool = True,
        track_history: bool = True,
    ):
        """
        Initialize fundamental neural network signal.

        Parameters:
            hidden_layers: Tuple of hidden layer sizes (default: (5, 5))
                          Paper's optimal: (5, 5) to avoid overfitting
            alpha: L2 regularization parameter (default: 0.5)
                   Balances bias-variance tradeoff on small sample
            max_iter: Maximum iterations for training (default: 500)
            standardize: If True, return z-scored alphas (default: True)
            track_history: If True, store signal generation history (default: True)
        """
        # Initialize BaseSignal
        super().__init__(
            name="sector_fundamental",
            standardize=standardize,
            track_history=track_history,
        )

        # Neural network configuration
        self.hidden_layers = hidden_layers
        self.alpha = alpha
        self.max_iter = max_iter

        # 11 neutralized fundamental factor columns (input features)
        self.feature_columns = [
            "pe_ratio_neutral",
            "pb_ratio_neutral",
            "ev_sales_neutral",
            "ev_ebit_neutral",
            "ev_ebitda_neutral",
            "dividend_yield_neutral",
            "gross_margin_neutral",
            "operating_margin_neutral",
            "profit_margin_neutral",
            "roa_neutral",
            "roe_neutral",
        ]

        # Model state
        self.model = None
        self.is_trained = False

    def train(self, X: np.ndarray, y: np.ndarray) -> None:
        """
        Train neural network on fundamental data.

        Parameters:
            X: Feature matrix, shape (n_samples, 11)
               Each row is 11 neutralized fundamental factors for one sector-quarter
            y: Target labels, shape (n_samples,)
               Binary: 1 = positive next-quarter return, 0 = negative

        Raises:
            ValueError: If X doesn't have 11 features or y has wrong shape
        """
        # Import sklearn here (optional dependency)
        try:
            from sklearn.neural_network import MLPClassifier
        except ImportError:
            raise ImportError(
                "scikit-learn is required for FundamentalSignal. "
                "Install it with: pip install scikit-learn"
            )

        # Validate inputs
        if X.shape[1] != 11:
            raise ValueError(
                f"Expected 11 features, got {X.shape[1]}. "
                f"Required features: {self.feature_columns}"
            )

        if len(y) != len(X):
            raise ValueError(
                f"X and y must have same length: X has {len(X)}, y has {len(y)}"
            )

        # Create and train MLPClassifier
        # Paper configuration: 2×5 hidden layers, L2 regularization, quasi-Newton solver
        self.model = MLPClassifier(
            hidden_layer_sizes=self.hidden_layers,
            activation='relu',           # ReLU activation (paper)
            solver='lbfgs',              # Quasi-Newton (good for small samples)
            alpha=self.alpha,            # L2 regularization
            max_iter=self.max_iter,
            random_state=42,             # Reproducibility
        )

        self.model.fit(X, y)
        self.is_trained = True

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Predict probability of positive return for each sector.

        Parameters:
            X: Feature matrix, shape (n_samples, 11)

        Returns:
            Array of probabilities [0, 1], shape (n_samples,)
            Each value is P(positive return | fundamentals)

        Raises:
            ValueError: If model hasn't been trained
        """
        if not self.is_trained or self.model is None:
            raise ValueError(
                "Model has not been trained. Call train() first."
            )

        # Get probabilities for class 1 (positive return)
        # model.predict_proba returns (n_samples, 2) array: [P(class 0), P(class 1)]
        probabilities = self.model.predict_proba(X)[:, 1]

        return probabilities

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[any],
        as_of: date,
    ) -> float:
        """
        Calculate raw signal (probability) for single sector.

        This method is called by BaseSignal.generate() and generate_batch().
        It extracts neutralized fundamental features and predicts probability.

        Parameters:
            inst_data: DataFrame with columns [ticker, date, *feature_columns]
                      Must contain 11 neutralized fundamental factor columns
            market_data: Not used for fundamental signal
            as_of: Calculation date (must match date in inst_data)

        Returns:
            Raw signal = predicted probability of positive return [0, 1]

        Raises:
            ValueError: If model not trained or missing features
        """
        if not self.is_trained:
            raise ValueError(
                "Model has not been trained. Call train() with fundamental "
                "data and next-quarter returns before generating signals."
            )

        # Filter to as_of date
        row = inst_data.filter(pl.col("date") == as_of)

        if len(row) == 0:
            raise ValueError(
                f"No data found for date {as_of} in inst_data"
            )

        # Validate feature columns exist
        missing_features = [
            col for col in self.feature_columns
            if col not in row.columns
        ]
        if missing_features:
            raise ValueError(
                f"Missing required features: {missing_features}. "
                f"Ensure fundamental data has been neutralized with "
                f"CrossSectionalNeutralizer."
            )

        # Extract features as numpy array
        features = row.select(self.feature_columns).to_numpy()[0]

        # Predict probability (reshape for single sample)
        probability = self.predict_proba(features.reshape(1, -1))[0]

        return probability

    def __repr__(self) -> str:
        """Return string representation."""
        trained_status = "trained" if self.is_trained else "untrained"
        return (
            f"FundamentalSignal("
            f"name='{self.name}', "
            f"hidden_layers={self.hidden_layers}, "
            f"alpha={self.alpha}, "
            f"{trained_status}, "
            f"standardize={self.standardize}"
            f")"
        )
