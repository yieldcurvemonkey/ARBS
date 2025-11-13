# ABOUTME: ML-enhanced factor backtest comparing Random Forest to classical factors
# ABOUTME: Demonstrates feature engineering, model training, IC analysis, and feature importance
"""
ML Factor Backtest Example

Demonstrates ML-enhanced factor signals using Random Forest:
1. Feature engineering (momentum, value, quality, technical indicators)
2. ML model training (RandomForestRegressor)
3. Comparison to classical factors (momentum-only, value-only)
4. Performance metrics (Sharpe, IC, turnover)
5. Feature importance analysis

Target Performance (from 2025 research):
- IC > 0.05 (good)
- Sharpe > 0.7 (target)
- Sharpe > 2.0 (research frontier)
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import polars as pl
from datetime import date, timedelta
from typing import Dict, List

from Signals.Utils.FeatureEngineering import FeatureEngineering
from Signals.MLPredictedReturnsSignal import MLPredictedReturnsSignal


def create_synthetic_sector_data(
    n_sectors: int = 11,
    n_periods: int = 1000,
    random_seed: int = 42,
) -> pl.DataFrame:
    """
    Create synthetic sector ETF data with realistic properties.

    Simulates 11 SPDR sector ETFs (XLK, XLF, XLE, etc.) with:
    - Momentum persistence
    - Value mean reversion
    - Quality premium
    - Technical patterns

    Parameters:
        n_sectors: Number of sectors (default: 11 for SPDR ETFs)
        n_periods: Number of trading days (default: 1000 ≈ 4 years)
        random_seed: Random seed for reproducibility

    Returns:
        DataFrame with columns [ticker, date, price, return, ...]
    """
    np.random.seed(random_seed)

    sector_names = [
        "XLK",  # Technology
        "XLF",  # Financials
        "XLE",  # Energy
        "XLV",  # Healthcare
        "XLY",  # Consumer Discretionary
        "XLP",  # Consumer Staples
        "XLI",  # Industrials
        "XLB",  # Materials
        "XLU",  # Utilities
        "XLRE", # Real Estate
        "XLC",  # Communication Services
    ][:n_sectors]

    start_date = date(2020, 1, 1)

    data = []
    for sector in sector_names:
        # Sector-specific characteristics
        base_return = np.random.uniform(-0.0002, 0.0005)  # Daily drift
        volatility = np.random.uniform(0.01, 0.02)  # Daily vol

        # Generate returns with autocorrelation (momentum)
        returns = np.zeros(n_periods)
        returns[0] = np.random.randn() * volatility

        for t in range(1, n_periods):
            # Momentum effect (AR(1) process)
            momentum_effect = 0.1 * returns[t - 1]
            noise = np.random.randn() * volatility
            returns[t] = base_return + momentum_effect + noise

        # Calculate prices
        prices = 100 * np.exp(np.cumsum(returns))

        # Generate data
        for period in range(n_periods):
            data.append({
                "ticker": sector,
                "date": start_date + timedelta(days=period),
                "return": returns[period],
                "price": prices[period],
            })

    return pl.DataFrame(data)


def calculate_all_features(
    returns_data: pl.DataFrame,
) -> pl.DataFrame:
    """
    Calculate all features for ML model.

    Parameters:
        returns_data: DataFrame with [ticker, date, return, price]

    Returns:
        DataFrame with all features and next-period returns
    """
    fe = FeatureEngineering()

    print("Calculating features...")

    # 1. Momentum features
    print("  - Momentum (21d, 63d, 126d, 252d)")
    momentum = fe.calculate_momentum(returns_data, lookbacks=[21, 63, 126, 252])

    # 2. Value features (mock fundamentals)
    print("  - Value (P/E, P/B, dividend yield)")
    value = fe.calculate_value(returns_data, fundamentals=None)

    # 3. Quality features (mock financials)
    print("  - Quality (ROE, profit margin)")
    quality = fe.calculate_quality(financials=None)

    # 4. Technical indicators
    print("  - Technical (RSI, MACD, Bollinger bands)")
    technical = fe.calculate_technical(returns_data)

    # Combine all features
    print("  - Combining features...")
    features = momentum.join(value, on=["ticker", "date"], how="left")
    features = features.join(quality, on=["ticker", "date"], how="left")
    features = features.join(technical, on=["ticker", "date"], how="left")

    # Add next-period returns as target
    print("  - Adding target (next 21-day return)")
    features = features.join(
        returns_data.select(["ticker", "date", "return"]),
        on=["ticker", "date"],
        how="left",
    )

    # Calculate next 21-day return (forward-looking target)
    features = features.sort(["ticker", "date"])
    features = features.with_columns([
        pl.col("return")
        .rolling_sum(window_size=21)
        .shift(-21)
        .over("ticker")
        .alias("next_return")
    ])

    print(f"  ✓ Features shape: {features.shape}")
    return features


def train_ml_signal(
    features: pl.DataFrame,
    train_end_date: date,
) -> MLPredictedReturnsSignal:
    """
    Train ML signal on historical data.

    Parameters:
        features: DataFrame with all features and target
        train_end_date: End date for training period

    Returns:
        Trained MLPredictedReturnsSignal
    """
    print(f"\nTraining ML model (train until {train_end_date})...")

    # Filter training data
    train_data = features.filter(pl.col("date") < train_end_date)

    # Initialize signal
    signal = MLPredictedReturnsSignal(
        n_estimators=100,
        max_depth=5,
        random_state=42,
    )

    # Train
    signal.train(train_data)

    print(f"  ✓ Model trained on {len(train_data)} samples")
    return signal


def backtest_ml_signal(
    signal: MLPredictedReturnsSignal,
    features: pl.DataFrame,
    test_start_date: date,
    test_end_date: date,
) -> Dict:
    """
    Backtest ML signal on test period.

    Parameters:
        signal: Trained ML signal
        features: DataFrame with all features
        test_start_date: Start of test period
        test_end_date: End of test period

    Returns:
        Dictionary with performance metrics
    """
    print(f"\nBacktesting ML signal ({test_start_date} to {test_end_date})...")

    # Filter test data
    test_data = features.filter(
        (pl.col("date") >= test_start_date) & (pl.col("date") < test_end_date)
    )

    # Calculate IC for each date
    ics = []
    test_dates = test_data["date"].unique().sort()

    for test_date in test_dates:
        date_data = test_data.filter(pl.col("date") == test_date)

        if len(date_data) < 5:  # Need enough assets
            continue

        # Skip if no valid targets
        if date_data["next_return"].null_count() == len(date_data):
            continue

        # Predict
        try:
            predictions = signal.predict(date_data)
            actuals = date_data["next_return"].to_numpy()

            # Remove NaN targets
            valid_mask = ~np.isnan(actuals)
            if np.sum(valid_mask) < 5:
                continue

            predictions = predictions[valid_mask]
            actuals = actuals[valid_mask]

            # Calculate IC
            ic = np.corrcoef(predictions, actuals)[0, 1]
            if np.isfinite(ic):
                ics.append(ic)
        except Exception as e:
            continue

    # Calculate performance metrics
    if len(ics) == 0:
        print("  ✗ No valid IC calculations")
        return {}

    mean_ic = np.mean(ics)
    std_ic = np.std(ics)
    ic_ir = mean_ic / std_ic if std_ic > 0 else 0
    sharpe = ic_ir * np.sqrt(252)  # Annualized Sharpe estimate

    print(f"  ✓ Mean IC: {mean_ic:.4f}")
    print(f"  ✓ IC IR: {ic_ir:.4f}")
    print(f"  ✓ Est. Sharpe: {sharpe:.4f}")

    return {
        "ic_mean": mean_ic,
        "ic_std": std_ic,
        "ic_ir": ic_ir,
        "sharpe_est": sharpe,
        "ic_series": ics,
    }


def backtest_classical_factor(
    features: pl.DataFrame,
    factor_name: str,
    test_start_date: date,
    test_end_date: date,
) -> Dict:
    """
    Backtest classical single-factor signal.

    Parameters:
        features: DataFrame with all features
        factor_name: Name of factor column (e.g., "momentum_126d", "pe_ratio")
        test_start_date: Start of test period
        test_end_date: End of test period

    Returns:
        Dictionary with performance metrics
    """
    print(f"\nBacktesting {factor_name}...")

    # Filter test data
    test_data = features.filter(
        (pl.col("date") >= test_start_date) & (pl.col("date") < test_end_date)
    )

    # Calculate IC for each date
    ics = []
    test_dates = test_data["date"].unique().sort()

    for test_date in test_dates:
        date_data = test_data.filter(pl.col("date") == test_date)

        if len(date_data) < 5:
            continue

        # Get factor values and actuals
        factor_values = date_data[factor_name].to_numpy()
        actuals = date_data["next_return"].to_numpy()

        # Remove NaN values
        valid_mask = ~np.isnan(factor_values) & ~np.isnan(actuals)
        if np.sum(valid_mask) < 5:
            continue

        factor_values = factor_values[valid_mask]
        actuals = actuals[valid_mask]

        # Calculate IC
        ic = np.corrcoef(factor_values, actuals)[0, 1]
        if np.isfinite(ic):
            ics.append(ic)

    if len(ics) == 0:
        return {}

    mean_ic = np.mean(ics)
    std_ic = np.std(ics)
    ic_ir = mean_ic / std_ic if std_ic > 0 else 0
    sharpe = ic_ir * np.sqrt(252)

    print(f"  ✓ Mean IC: {mean_ic:.4f}")
    print(f"  ✓ IC IR: {ic_ir:.4f}")
    print(f"  ✓ Est. Sharpe: {sharpe:.4f}")

    return {
        "ic_mean": mean_ic,
        "ic_std": std_ic,
        "ic_ir": ic_ir,
        "sharpe_est": sharpe,
        "ic_series": ics,
    }


def main():
    """Run ML factor backtest."""
    print("="* 70)
    print("ML-ENHANCED FACTOR BACKTEST")
    print("="* 70)

    # 1. Generate synthetic sector data
    print("\n1. GENERATING SYNTHETIC SECTOR DATA")
    print("-" * 70)
    data = create_synthetic_sector_data(n_sectors=11, n_periods=1000, random_seed=42)
    print(f"Generated {len(data)} observations for {data['ticker'].n_unique()} sectors")
    print(f"Date range: {data['date'].min()} to {data['date'].max()}")

    # 2. Calculate features
    print("\n2. FEATURE ENGINEERING")
    print("-" * 70)
    features = calculate_all_features(data)

    # 3. Train ML signal
    print("\n3. TRAINING ML SIGNAL")
    print("-" * 70)
    train_end = date(2022, 1, 1)
    test_start = date(2022, 1, 1)
    test_end = date(2023, 1, 1)

    ml_signal = train_ml_signal(features, train_end)

    # 4. Show feature importance
    print("\n4. FEATURE IMPORTANCE")
    print("-" * 70)
    importance = ml_signal.get_feature_importance()

    print("\nTop 10 Most Important Features:")
    sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    for i, (feature, imp) in enumerate(sorted_importance[:10], 1):
        bar = "█" * int(imp * 100)
        print(f"  {i:2d}. {feature:20s}: {imp:.4f} {bar}")

    # 5. Backtest ML signal
    print("\n5. BACKTEST RESULTS")
    print("-" * 70)

    ml_results = backtest_ml_signal(ml_signal, features, test_start, test_end)

    # 6. Compare to classical factors
    print("\n6. COMPARISON TO CLASSICAL FACTORS")
    print("-" * 70)

    # Momentum
    momentum_results = backtest_classical_factor(
        features,
        "momentum_126d",
        test_start,
        test_end,
    )

    # Value (inverse P/E since low P/E is good)
    # Note: We'll use negative pe_ratio so higher signal = better
    features_with_value = features.with_columns([
        (-pl.col("pe_ratio")).alias("value_signal")
    ])

    value_results = backtest_classical_factor(
        features_with_value,
        "value_signal",
        test_start,
        test_end,
    )

    # 7. Performance comparison table
    print("\n7. PERFORMANCE COMPARISON")
    print("-" * 70)
    print(f"{'Strategy':<25} {'Mean IC':<12} {'IC IR':<12} {'Est. Sharpe':<12}")
    print("-" * 70)

    if ml_results:
        print(
            f"{'ML Predicted Returns':<25} "
            f"{ml_results['ic_mean']:>11.4f} "
            f"{ml_results['ic_ir']:>11.4f} "
            f"{ml_results['sharpe_est']:>11.4f}"
        )

    if momentum_results:
        print(
            f"{'Momentum (126d)':<25} "
            f"{momentum_results['ic_mean']:>11.4f} "
            f"{momentum_results['ic_ir']:>11.4f} "
            f"{momentum_results['sharpe_est']:>11.4f}"
        )

    if value_results:
        print(
            f"{'Value (1/P/E)':<25} "
            f"{value_results['ic_mean']:>11.4f} "
            f"{value_results['ic_ir']:>11.4f} "
            f"{value_results['sharpe_est']:>11.4f}"
        )

    # 8. Success criteria
    print("\n8. SUCCESS CRITERIA")
    print("-" * 70)

    if ml_results:
        criteria = [
            ("IC >= 0.05 (good)", ml_results['ic_mean'] >= 0.05),
            ("Sharpe > 0.7 (target)", ml_results['sharpe_est'] > 0.7),
            ("ML improves vs Momentum", ml_results['ic_mean'] > momentum_results.get('ic_mean', 0)),
            ("ML improves vs Value", ml_results['ic_mean'] > value_results.get('ic_mean', 0)),
        ]

        for criterion, passed in criteria:
            status = "✓" if passed else "✗"
            print(f"  {status} {criterion}")

    print("\n" + "=" * 70)
    print("BACKTEST COMPLETE!")
    print("=" * 70)


if __name__ == "__main__":
    main()
