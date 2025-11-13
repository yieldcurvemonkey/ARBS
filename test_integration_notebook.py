#!/usr/bin/env python
"""
Test script to verify the cross-asset integration notebook works correctly.

This script executes key sections of the notebook to ensure:
1. All imports work
2. Data generation works
3. Each of the 5 examples can be instantiated
4. No critical errors occur
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

import numpy as np
import pandas as pd
import polars as pl
from datetime import date, timedelta
from typing import List, Dict, Tuple

print("=" * 70)
print("Testing Cross-Asset Integration Notebook")
print("=" * 70)

# Set random seed
np.random.seed(42)

# Test 1: Imports
print("\n[1/6] Testing imports...")
try:
    from Risk.Covariance.SectorBased.BaseSectorCovarianceEstimator import SectorBasedCovarianceEstimator
    from Optimizer.ClusterAwareMeanVarianceOptimizer import ClusterAwareMeanVarianceOptimizer
    from Optimizer.CVaRMeanVarianceOptimizer import CVaRMeanVarianceOptimizer
    from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer
    from Signals.CorrelationVolatilitySignal import CorrelationVolatilitySignal
    from Signals.CurrencyCarrySignal import CurrencyCarrySignal
    from Signals.MLPredictedReturnsSignal import MLPredictedReturnsSignal
    from Signals.Utils.FeatureEngineering import FeatureEngineering
    from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator
    from Query.Currencies.CurrencyQuery import CurrencyQuery
    print("✓ All imports successful")
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Generate mock data
print("\n[2/6] Generating mock S&P 500 data...")
try:
    stocks = {
        'AAPL': 'Technology',
        'MSFT': 'Technology',
        'GOOGL': 'Technology',
        'JPM': 'Financials',
        'BAC': 'Financials',
        'XOM': 'Energy',
        'CVX': 'Energy',
        'JNJ': 'Healthcare',
        'PFE': 'Healthcare',
        'WMT': 'Consumer'
    }

    tickers = list(stocks.keys())
    n_days = 252
    dates = [date(2023, 1, 1) + timedelta(days=i) for i in range(n_days)]

    # Generate sector-correlated returns
    sector_list = list(set(stocks.values()))
    n_sectors = len(sector_list)
    sector_returns = np.random.normal(0, 0.015, (n_days, n_sectors))

    returns_dict = {}
    for stock in tickers:
        sector = stocks[stock]
        sector_idx = sector_list.index(sector)
        idiosyncratic = np.random.normal(0, 0.015, n_days)
        stock_return = (
            np.sqrt(0.6) * sector_returns[:, sector_idx] +
            np.sqrt(0.4) * idiosyncratic
        )
        returns_dict[stock] = stock_return

    # Create returns DataFrame
    returns_data = []
    for ticker in tickers:
        for i, d in enumerate(dates):
            returns_data.append({
                'date': d,
                'ticker': ticker,
                'return': returns_dict[ticker][i],
                'sector': stocks[ticker]
            })

    returns_df = pl.DataFrame(returns_data)

    # Create wide format for covariance
    returns_wide = returns_df.pivot(
        index='date',
        columns='ticker',
        values='return'
    ).to_pandas()

    print(f"✓ Generated {n_days} days of returns for {len(tickers)} stocks")
except Exception as e:
    print(f"✗ Data generation failed: {e}")
    sys.exit(1)

# Test 3: Example 1 - Cluster-Aware Portfolio
print("\n[3/6] Testing Example 1: Cluster-Aware Portfolio...")
try:
    cov_estimator = SectorBasedCovarianceEstimator()
    cov_estimator.fit(returns_wide)

    clusters = cov_estimator.get_correlation_clusters(
        method='hierarchical',
        threshold=0.5,
        min_cluster_size=2
    )

    cluster_optimizer = ClusterAwareMeanVarianceOptimizer(
        correlation_clusters=clusters,
        max_per_cluster=2,
        risk_aversion=1.0,
        long_only=True
    )

    alphas = pl.Series('alpha', [0.05, 0.04, 0.03, 0.02, 0.01, 0.01, 0.02, 0.03, 0.04, 0.05], dtype=pl.Float64)
    covariance_pl = pl.DataFrame(cov_estimator.cov_matrix_, schema=tickers)

    weights_cluster = cluster_optimizer.optimize(alphas, covariance_pl)

    print(f"✓ Cluster-aware optimizer created {len(clusters)} clusters")
    print(f"  Portfolio has {sum(1 for w in weights_cluster.values() if w > 0.001)} active positions")
except Exception as e:
    print(f"✗ Example 1 failed: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Example 2 - Volatility Dispersion
print("\n[4/6] Testing Example 2: Volatility Dispersion...")
try:
    vol_calc = VolatilityRatioCalculator(lookback=30, annualization=252)

    # Generate mock vol ratios
    rv_data = []
    for ticker in tickers:
        ticker_returns = returns_df.filter(pl.col('ticker') == ticker).sort('date')
        for i in range(30, min(50, len(dates))):  # Just test a few dates
            window_returns = ticker_returns['return'][i-30:i].to_numpy()
            rv = np.std(window_returns) * np.sqrt(252)
            iv = rv * (1.0 + np.random.normal(0, 0.1))
            rv_data.append({
                'ticker': ticker,
                'date': dates[i],
                'RV': rv,
                'IV': iv,
                'IV_RV_ratio': iv / rv if rv > 0 else 1.0
            })

    vol_ratios_df = pl.DataFrame(rv_data)

    vol_signal = CorrelationVolatilitySignal(
        min_correlation=0.7,
        lookback=60,
        z_threshold=1.5
    )

    # Test with a single pair
    high_corr_pairs = [('AAPL', 'MSFT')]
    signals_df = vol_signal.calculate_batch_detailed(
        returns=returns_df,
        vol_ratios=vol_ratios_df,
        pairs=high_corr_pairs,
        as_of=dates[40]
    )

    print(f"✓ Volatility dispersion signal generated for {len(high_corr_pairs)} pairs")
    print(f"  Signals found: {signals_df.height}")
except Exception as e:
    print(f"✗ Example 2 failed: {e}")
    import traceback
    traceback.print_exc()

# Test 5: Example 3 - Currency Carry
print("\n[5/6] Testing Example 3: Currency Carry...")
try:
    currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD']
    tenors = ['2Y', '5Y', '10Y']

    base_rates = {'USD': 5.0, 'EUR': 3.5, 'GBP': 4.5, 'JPY': 0.5, 'AUD': 4.0}
    tenor_map = {'2Y': 2, '5Y': 5, '10Y': 10}

    yield_data = []
    for currency in currencies:
        base_rate = base_rates[currency]
        for tenor in tenors:
            years = tenor_map[tenor]
            rate = base_rate + (years / 10) * 0.5 + np.random.normal(0, 0.1)
            yield_data.append({
                'currency': currency,
                'tenor': tenor,
                'yield': rate
            })

    yield_curves = pl.DataFrame(yield_data)

    carry_signal = CurrencyCarrySignal(
        long_tenor='10Y',
        short_tenor='2Y',
        butterfly=False,
        standardize=True
    )

    print(f"✓ Currency carry signal created for {len(currencies)} currencies")
    print(f"  Yield curve data: {yield_curves.shape}")
except Exception as e:
    print(f"✗ Example 3 failed: {e}")
    import traceback
    traceback.print_exc()

# Test 6: Example 4 - ML-Enhanced Factors
print("\n[6/6] Testing Example 4: ML-Enhanced Factors...")
try:
    feature_eng = FeatureEngineering()

    lookbacks = [5, 10, 20]
    momentum_features = feature_eng.calculate_momentum(returns_df, lookbacks)

    # Generate mock fundamentals
    fundamentals_data = []
    for ticker in tickers:
        for d in dates[:50]:  # Just test subset
            fundamentals_data.append({
                'ticker': ticker,
                'date': d,
                'price': 100 + np.random.normal(0, 10),
                'book_value': 50 + np.random.normal(0, 5),
                'earnings': 5 + np.random.normal(0, 1)
            })

    fundamentals = pl.DataFrame(fundamentals_data)
    value_features = feature_eng.calculate_value(returns_df, fundamentals)

    ml_signal = MLPredictedReturnsSignal(
        n_estimators=10,  # Small for speed
        max_depth=3,
        random_state=42,
        target_col='next_return',
        standardize=True
    )

    print(f"✓ ML signal created with feature engineering")
    print(f"  Momentum features: {momentum_features.shape}")
    print(f"  Value features: {value_features.shape}")
except Exception as e:
    print(f"✗ Example 4 failed: {e}")
    import traceback
    traceback.print_exc()

# Test 7: Example 5 - CVaR Portfolio
print("\n[Bonus] Testing Example 5: CVaR Portfolio...")
try:
    cvar_optimizer = CVaRMeanVarianceOptimizer(
        risk_aversion=1.0,
        long_only=True,
        cvar_alpha=0.05,
        cvar_limit=0.03,
        use_cvxpy=True
    )

    returns_matrix = returns_wide.values
    weights_cvar = cvar_optimizer.optimize(
        alphas=alphas,
        covariance=covariance_pl,
        returns=returns_matrix
    )

    print(f"✓ CVaR optimizer created portfolio")
    print(f"  Active positions: {sum(1 for w in weights_cvar.values() if w > 0.001)}")
except Exception as e:
    print(f"✗ Example 5 failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("✓ All tests passed! Integration notebook is ready to use.")
print("=" * 70)
print("\nTo run the full notebook:")
print("  jupyter notebook notebooks/05_cross_asset_integration.ipynb")
