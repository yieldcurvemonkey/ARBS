# ABOUTME: Run portfolio validation on real S&P 500 data
# ABOUTME: Loads sp500_real_data.parquet and runs full validation suite

"""
Real Data Validation

Loads real S&P 500 data and validates all paper claims.

Usage:
  1. First load data using one of the load_*.py scripts
  2. This creates sp500_real_data.parquet
  3. Run: python validate_on_real_data.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import polars as pl
import numpy as np
from portfolio_performance_validation import (
    validate_model,
    SampleCovariance,
    LedoitWolfShrinkage,
    BlockDiagonalCovariance,
    TwoStepCovariance,
    StochasticBlockCovariance,
)


def load_real_data() -> tuple:
    """Load real data from parquet file."""
    data_file = Path(__file__).parent / "sp500_real_data.parquet"

    if not data_file.exists():
        print("ERROR: Real data file not found!")
        print(f"Expected: {data_file}")
        print("\nPlease run one of the data loading scripts first:")
        print("  python load_alphavantage.py YOUR_KEY")
        print("  python load_quandl.py YOUR_KEY")
        print("  python load_yahoo_cookies.py")
        print("  python load_csv_manual.py")
        print("\nSee README_DATA_LOADING.md for details")
        sys.exit(1)

    print("="*80)
    print("LOADING REAL S&P 500 DATA")
    print("="*80)
    print(f"\nData file: {data_file}")
    print(f"Size: {data_file.stat().st_size / 1024 / 1024:.1f} MB\n")

    df = pl.read_parquet(data_file)

    print(f"✓ Loaded {len(df):,} observations")
    print(f"✓ Tickers: {df['ticker'].n_unique()}")
    print(f"✓ Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"✓ Sectors: {df['sector'].n_unique()}")

    # Split train/test
    dates = sorted(df['date'].unique().to_list())
    split_idx = int(len(dates) * 0.67)  # 67% train, 33% test

    train_dates = dates[:split_idx]
    test_dates = dates[split_idx:]

    train_data = df.filter(pl.col("date").is_in(train_dates))
    test_data = df.filter(pl.col("date").is_in(test_dates))

    print(f"\nTrain/Test Split:")
    print(f"  Training: {len(train_dates)} days ({train_dates[0]} to {train_dates[-1]})")
    print(f"  Test: {len(test_dates)} days ({test_dates[0]} to {test_dates[-1]})")

    return train_data, test_data


def run_validation():
    """Run complete validation on real data."""
    train_data, test_data = load_real_data()

    print("\n" + "="*80)
    print("RUNNING PORTFOLIO PERFORMANCE VALIDATION ON REAL DATA")
    print("="*80)

    # Models to compare
    models = [
        ("1. Sample Covariance", SampleCovariance(), False),
        ("2. Ledoit-Wolf", LedoitWolfShrinkage(), False),
        ("3. BlockDiagonal (Paper 2)", BlockDiagonalCovariance(n_factors=5), True),
        ("4. TwoStep (Paper 1)", TwoStepCovariance(n_clusters=5, rmt_filter=True), True),
        ("5. StochasticBlock (Paper 3)", StochasticBlockCovariance(alpha=0.7), True),
    ]

    results = []
    for name, estimator, use_long_format in models:
        result = validate_model(name, estimator, train_data, test_data, use_long_format)
        results.append(result)

    # Print comparison table
    print("\n" + "="*80)
    print("COMPARISON TABLE - REAL S&P 500 DATA")
    print("="*80)
    print(f"\n{'Model':<30} {'HHI':<10} {'Leverage':<10} {'RDI':<10} {'Sharpe':<10} {'R²_out':<10}")
    print("-"*80)

    for r in results:
        print(f"{r['name']:<30} {r['hhi']:<10.4f} {r['leverage']:<10.2f} {r['rdi']:<10.3f} {r['sharpe']:<10.3f} {r['r2_out']:<10.3f}")

    # Analysis against paper claims
    print("\n" + "="*80)
    print("PAPER CLAIMS VS ACTUAL RESULTS (REAL DATA)")
    print("="*80)

    baseline_hhi = results[0]['hhi']
    baseline_sharpe = results[0]['sharpe']
    baseline_leverage = results[0]['leverage']

    print("\n📊 Paper 1 (García-Medina - TwoStep)")
    print(f"   Claim: 'Best diversification and leverage'")
    print(f"   HHI: {results[3]['hhi']:.4f} vs Baseline {baseline_hhi:.4f}")
    print(f"   → {((baseline_hhi - results[3]['hhi']) / baseline_hhi * 100):+.1f}% change")
    print(f"   Leverage: {results[3]['leverage']:.2f} vs Baseline {baseline_leverage:.2f}")
    print(f"   → {((baseline_leverage - results[3]['leverage']) / baseline_leverage * 100):+.1f}% change")
    verdict1 = "✅ VALIDATED" if (results[3]['hhi'] < baseline_hhi and results[3]['leverage'] < baseline_leverage) else "❌ NOT VALIDATED"
    print(f"   Verdict: {verdict1}")

    print("\n📊 Paper 2 (Žignić - BlockDiagonal)")
    print(f"   Claim: 'Excellent out-of-sample Sharpe ratios'")
    print(f"   Sharpe: {results[2]['sharpe']:.3f} vs Baseline {baseline_sharpe:.3f}")
    print(f"   → {((results[2]['sharpe'] - baseline_sharpe) / abs(baseline_sharpe) * 100):+.1f}% change")
    verdict2 = "✅ VALIDATED" if results[2]['sharpe'] > baseline_sharpe else "❌ NOT VALIDATED"
    print(f"   Verdict: {verdict2}")

    print("\n📊 Paper 3 (Chen - StochasticBlock)")
    print(f"   Claim: 'Captures cross-sector correlations'")
    print(f"   HHI: {results[4]['hhi']:.4f} vs Baseline {baseline_hhi:.4f}")
    print(f"   → {((baseline_hhi - results[4]['hhi']) / baseline_hhi * 100):+.1f}% change")
    print(f"   Sharpe: {results[4]['sharpe']:.3f} vs Baseline {baseline_sharpe:.3f}")
    print(f"   → {((results[4]['sharpe'] - baseline_sharpe) / abs(baseline_sharpe) * 100):+.1f}% change")
    verdict3 = "✅ VALIDATED" if (results[4]['hhi'] < baseline_hhi and results[4]['sharpe'] > baseline_sharpe) else "❌ NOT VALIDATED"
    print(f"   Verdict: {verdict3}")

    print("\n" + "="*80)
    print("VALIDATION COMPLETE")
    print("="*80)

    # Save results
    results_file = Path(__file__).parent / "validation_results_real_data.txt"
    with open(results_file, 'w') as f:
        f.write("REAL DATA VALIDATION RESULTS\n")
        f.write("="*80 + "\n\n")
        f.write(f"Data: {train_data['ticker'].n_unique()} tickers\n")
        f.write(f"Train: {train_data['date'].n_unique()} days\n")
        f.write(f"Test: {test_data['date'].n_unique()} days\n\n")

        for r in results:
            f.write(f"{r['name']}\n")
            f.write(f"  HHI: {r['hhi']:.4f}\n")
            f.write(f"  Leverage: {r['leverage']:.2f}\n")
            f.write(f"  RDI: {r['rdi']:.3f}\n")
            f.write(f"  Sharpe: {r['sharpe']:.3f}\n")
            f.write(f"  R²_out: {r['r2_out']:.3f}\n\n")

        f.write(f"\nPaper 1: {verdict1}\n")
        f.write(f"Paper 2: {verdict2}\n")
        f.write(f"Paper 3: {verdict3}\n")

    print(f"\n✓ Results saved to {results_file}")

    return results


if __name__ == "__main__":
    results = run_validation()
