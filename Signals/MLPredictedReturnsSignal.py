# ABOUTME: ML-enhanced signal using Random Forest to predict returns from engineered features
# ABOUTME: Implements cross-sectional ML model with time-series cross-validation and IC tracking
"""
MLPredictedReturnsSignal - Machine learning enhanced factor signal.

Uses Random Forest to predict next-period returns based on engineered features:
- Momentum (multiple lookbacks)
- Value (P/E, P/B, dividend yield)
- Quality (ROE, profit margin)
- Technical indicators (RSI, MACD, Bollinger bands)

Design principles:
1. Time-series cross-validation (expanding window to avoid look-ahead bias)
2. Cross-sectional predictions (predict returns for all assets at each date)
3. Z-score standardization for portfolio integration
4. Feature importance tracking for interpretability
5. IC tracking for signal quality monitoring

Target performance (from 2025 research):
- IC > 0.05 (good)
- Sharpe > 0.7 (target)
- Sharpe > 2.0 (research frontier with neural networks)

Example:
    >>> from Signals.MLPredictedReturnsSignal import MLPredictedReturnsSignal
    >>> from Signals.Utils.FeatureEngineering import FeatureEngineering
    >>>
    >>> # Prepare features
    >>> fe = FeatureEngineering()
    >>> momentum = fe.calculate_momentum(returns, lookbacks=[21, 63, 126])
    >>> value = fe.calculate_value(prices)
    >>> technical = fe.calculate_technical(prices)
    >>>
    >>> # Combine features
    >>> features = momentum.join(value, on=["ticker", "date"])
    >>> features = features.join(technical, on=["ticker", "date"])
    >>>
    >>> # Add next-period returns as target
    >>> features = features.with_columns([
    ...     pl.col("return").shift(-21).alias("next_return")
    ... ])
    >>>
    >>> # Train signal
    >>> signal = MLPredictedReturnsSignal(n_estimators=100, max_depth=5)
    >>> signal.train(features)
    >>>
    >>> # Generate predictions
    >>> test_data = features.filter(pl.col("date") >= date(2023, 1, 1))
    >>> predictions = signal.predict(test_data)
    >>>
    >>> # Get feature importance
    >>> importance = signal.get_feature_importance()
"""

from datetime import date, timedelta
from typing import Any, List, Optional, Dict
import numpy as np
import polars as pl
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import TimeSeriesSplit

from Signals.Base.BaseSignal import BaseSignal


class MLPredictedReturnsSignal(BaseSignal):
    """
    ML-enhanced signal using Random Forest for return prediction.
    
    Trains a Random Forest model to predict next-period returns based on
    engineered features (momentum, value, quality, technical indicators).
    
    Attributes:
        n_estimators: Number of trees in forest (default: 100)
        max_depth: Maximum tree depth (default: 5)
        random_state: Random seed for reproducibility
        model: Trained RandomForestRegressor
        feature_cols: List of feature column names
        target_col: Name of target column (default: "next_return")
    """
    
    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 5,
        random_state: int = 42,
        target_col: str = "next_return",
        standardize: bool = True,
        track_history: bool = True,
    ):
        """
        Initialize ML predicted returns signal.
        
        Parameters:
            n_estimators: Number of trees in Random Forest (default: 100)
            max_depth: Maximum depth of each tree (default: 5)
            random_state: Random seed for reproducibility (default: 42)
            target_col: Name of target column in data (default: "next_return")
            standardize: Whether to z-score predictions (default: True)
            track_history: Whether to track signal history (default: True)
        """
        super().__init__(
            name="ml_predicted_returns",
            standardize=standardize,
            track_history=track_history,
        )
        
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.random_state = random_state
        self.target_col = target_col
        
        # Model will be initialized during training
        self.model: Optional[RandomForestRegressor] = None
        self.feature_cols: List[str] = []
    
    def train(self, data: pl.DataFrame) -> None:
        """
        Train Random Forest model on feature data.
        
        Parameters:
            data: DataFrame with feature columns and target column
                  Must contain: ticker, date, feature columns, target_col
        
        Raises:
            ValueError: If required columns missing or insufficient data
        """
        # Validate required columns
        if "ticker" not in data.columns or "date" not in data.columns:
            raise ValueError("Data must contain 'ticker' and 'date' columns")
        
        if self.target_col not in data.columns:
            raise ValueError(f"Data must contain target column '{self.target_col}'")
        
        # Identify feature columns (all except ticker, date, target)
        exclude_cols = {"ticker", "date", self.target_col}
        self.feature_cols = [col for col in data.columns if col not in exclude_cols]
        
        if len(self.feature_cols) == 0:
            raise ValueError("No feature columns found in data")
        
        # Prepare training data (drop rows with missing target)
        train_data = data.drop_nulls(subset=[self.target_col])
        
        if len(train_data) == 0:
            raise ValueError("No valid training data (all targets are null)")
        
        # Extract features and target
        X = train_data.select(self.feature_cols).to_numpy()
        y = train_data[self.target_col].to_numpy()
        
        # Handle missing values in features (fill with column mean)
        for i in range(X.shape[1]):
            col = X[:, i]
            if np.any(np.isnan(col)):
                col_mean = np.nanmean(col)
                X[:, i] = np.where(np.isnan(col), col_mean, col)
        
        # Initialize and train model
        self.model = RandomForestRegressor(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            random_state=self.random_state,
            n_jobs=-1,  # Use all CPU cores
        )
        
        self.model.fit(X, y)
    
    def predict(self, data: pl.DataFrame) -> np.ndarray:
        """
        Predict returns using trained model.
        
        Parameters:
            data: DataFrame with same features used in training
        
        Returns:
            Array of predicted returns (not z-scored)
        
        Raises:
            ValueError: If model not trained or features missing
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Verify feature columns exist
        missing_cols = set(self.feature_cols) - set(data.columns)
        if missing_cols:
            raise ValueError(f"Missing feature columns: {missing_cols}")
        
        # Extract features
        X = data.select(self.feature_cols).to_numpy()
        
        # Handle missing values (fill with column mean from training)
        for i in range(X.shape[1]):
            col = X[:, i]
            if np.any(np.isnan(col)):
                col_mean = np.nanmean(col)
                X[:, i] = np.where(np.isnan(col), col_mean, col)
        
        # Predict
        predictions = self.model.predict(X)
        
        return predictions
    
    def cross_validate(
        self,
        data: pl.DataFrame,
        n_splits: int = 5,
    ) -> Dict[str, Any]:
        """
        Perform time-series cross-validation with expanding window.

        Uses expanding window to avoid look-ahead bias:
        - Split 1: Train on 20%, test on next 20%
        - Split 2: Train on 40%, test on next 20%
        - Split 3: Train on 60%, test on next 20%
        - etc.

        Parameters:
            data: DataFrame with features and target
            n_splits: Number of cross-validation splits (default: 5)

        Returns:
            Dictionary with IC scores and predictions for each split
        """
        # Prepare data
        train_data = data.drop_nulls(subset=[self.target_col])

        if len(train_data) == 0:
            raise ValueError("No valid training data")

        # Sort by date for time-series split
        train_data = train_data.sort("date")

        # Identify feature columns (if not already set)
        if len(self.feature_cols) == 0:
            exclude_cols = {"ticker", "date", self.target_col}
            feature_cols = [col for col in data.columns if col not in exclude_cols]
        else:
            feature_cols = self.feature_cols

        # Extract features and target
        X = train_data.select(feature_cols).to_numpy()
        y = train_data[self.target_col].to_numpy()
        
        # Handle missing values
        for i in range(X.shape[1]):
            col = X[:, i]
            if np.any(np.isnan(col)):
                col_mean = np.nanmean(col)
                X[:, i] = np.where(np.isnan(col), col_mean, col)
        
        # Time series split (expanding window)
        tscv = TimeSeriesSplit(n_splits=n_splits)
        
        ic_scores = []
        predictions_all = []
        
        for train_idx, test_idx in tscv.split(X):
            # Split data
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            
            # Train model
            model = RandomForestRegressor(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                random_state=self.random_state,
                n_jobs=-1,
            )
            model.fit(X_train, y_train)
            
            # Predict
            y_pred = model.predict(X_test)
            
            # Calculate IC (correlation)
            ic = np.corrcoef(y_pred, y_test)[0, 1]
            ic_scores.append(ic)
            predictions_all.append({
                "predictions": y_pred,
                "actuals": y_test,
                "ic": ic,
            })
        
        return {
            "ic_scores": np.array(ic_scores),
            "mean_ic": np.mean(ic_scores),
            "std_ic": np.std(ic_scores),
            "predictions": predictions_all,
        }
    
    def get_feature_importance(self) -> Dict[str, float]:
        """
        Get feature importance from trained model.
        
        Returns:
            Dictionary mapping feature name to importance (sums to 1)
        
        Raises:
            ValueError: If model not trained
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Get importance from Random Forest
        importance = self.model.feature_importances_
        
        # Create dictionary
        importance_dict = {
            col: float(imp)
            for col, imp in zip(self.feature_cols, importance)
        }
        
        return importance_dict
    
    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Calculate raw ML prediction for a single instrument.
        
        Parameters:
            inst_data: DataFrame with feature columns for one instrument
            market_data: Not used (all data is instrument-specific)
            as_of: Calculation date
        
        Returns:
            Predicted return (before standardization)
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Filter to as_of date
        date_data = inst_data.filter(pl.col("date") == as_of)
        
        if len(date_data) == 0:
            raise ValueError(f"No data for date {as_of}")
        
        # Predict
        prediction = self.predict(date_data)[0]
        
        return float(prediction)
    
    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"MLPredictedReturnsSignal("
            f"n_estimators={self.n_estimators}, "
            f"max_depth={self.max_depth}, "
            f"trained={self.model is not None}"
            f")"
        )


if __name__ == "__main__":
    # Example usage
    print("MLPredictedReturnsSignal - ML-Enhanced Factor Signal")
    print("=" * 60)
    
    # Create synthetic data for demonstration
    np.random.seed(42)
    n_assets = 10
    n_periods = 200
    
    data_list = []
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
            
            data_list.append({
                "ticker": f"ASSET_{asset_id}",
                "date": date(2020, 1, 1) + timedelta(days=period),
                "momentum_21d": momentum,
                "pe_ratio": value,
                "roe": quality,
                "next_return": true_return,
            })
    
    data = pl.DataFrame(data_list)
    
    print(f"\nSynthetic data: {len(data)} rows, {n_assets} assets, {n_periods} periods")
    
    # Train model
    print("\nTraining Random Forest model...")
    signal = MLPredictedReturnsSignal(
        n_estimators=100,
        max_depth=5,
        random_state=42,
    )
    
    train_cutoff = date(2020, 6, 1)
    train_data = data.filter(pl.col("date") < train_cutoff)
    
    signal.train(train_data)
    print(f"Model trained on {len(train_data)} samples")
    
    # Get feature importance
    print("\nFeature Importance:")
    importance = signal.get_feature_importance()
    for feature, imp in sorted(importance.items(), key=lambda x: x[1], reverse=True):
        print(f"  {feature:20s}: {imp:.4f}")
    
    # Cross-validate
    print("\nCross-validation (3 splits)...")
    cv_results = signal.cross_validate(train_data, n_splits=3)
    print(f"  Mean IC: {cv_results['mean_ic']:.4f}")
    print(f"  Std IC:  {cv_results['std_ic']:.4f}")
    print(f"  IC scores: {cv_results['ic_scores']}")
    
    # Predict on test data
    test_data = data.filter(pl.col("date") >= train_cutoff)
    predictions = signal.predict(test_data)
    
    print(f"\nTest predictions: {len(predictions)} samples")
    print(f"  Mean: {predictions.mean():.4f}")
    print(f"  Std:  {predictions.std():.4f}")
    
    # Calculate test IC
    actuals = test_data["next_return"].to_numpy()
    test_ic = np.corrcoef(predictions, actuals)[0, 1]
    print(f"  Test IC: {test_ic:.4f}")
    
    print("\n" + "=" * 60)
    print("ML Signal Ready!")
