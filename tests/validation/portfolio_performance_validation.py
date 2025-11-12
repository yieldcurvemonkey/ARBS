# ABOUTME: Comprehensive portfolio performance validation comparing all covariance models
# ABOUTME: Measures Sharpe ratios, HHI, Leverage, RDI, and R²_out to verify paper claims
"""
Portfolio Performance Validation

This script validates that our covariance models produce the performance
improvements claimed in the papers:

Paper 1 (García-Medina 2024):
- Lower HHI (better diversification)
- Lower Leverage (less short-selling)
- Better R²_out (out-of-sample prediction)

Paper 2 (Žignić et al. 2024):
- Higher Sharpe ratios
- Better out-of-sample portfolio performance

Comparison Models:
1. Sample Covariance (baseline)
2. Ledoit-Wolf Full Matrix (baseline)
3. BlockDiagonalCovariance (Paper 2)
4. TwoStepCovariance (Paper 1)
5. StochasticBlockCovariance (Paper 3)
"""

import numpy as np
import polars as pl
from typing import Dict, Tuple
from datetime import date, timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from Risk.Covariance.SampleCovariance import SampleCovariance
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Risk.Covariance.SectorBased.BlockDiagonal.BlockDiagonalCovariance import BlockDiagonalCovariance
from Risk.Covariance.SectorBased.TwoStep.TwoStepCovariance import TwoStepCovariance
from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import StochasticBlockCovariance
from Analysis.RiskMetrics import (
    herfindahl_hirschman_index,
    leverage,
    risk_diversification_index,
)


def generate_realistic_sector_data(
    n_sectors: int = 5,
    assets_per_sector: int = 10,
    n_train: int = 500,
    n_test: int = 250,
    seed: int = 42,
) -> Tuple[pl.DataFrame, pl.DataFrame]:
    """
    Generate realistic returns with sector structure.

    Structure matches empirical equity data:
    - Market factor (explains ~30% variance)
    - Sector factors (explain ~20% variance)
    - Idiosyncratic noise (remaining ~50%)
    """
    np.random.seed(seed)

    n_total = n_sectors * assets_per_sector
    n_obs = n_train + n_test

    # Generate factors
    market_factor = np.random.normal(0, 0.015, n_obs)  # Market volatility 1.5% daily
    sector_factors = np.random.normal(0, 0.01, (n_sectors, n_obs))  # Sector vol 1%

    # Factor loadings (beta to market)
    market_betas = np.random.uniform(0.7, 1.3, n_total)

    # Sector loadings
    sector_betas = np.random.uniform(0.5, 1.0, n_total)

    # Generate returns
    data = []
    start_date = date(2020, 1, 1)

    for t in range(n_obs):
        current_date = start_date + timedelta(days=t)

        for s_idx in range(n_sectors):
            for a_idx in range(assets_per_sector):
                asset_idx = s_idx * assets_per_sector + a_idx
                ticker = f"S{s_idx}_A{a_idx}"

                # Return = market_beta * market + sector_beta * sector + idiosyncratic
                ret = (
                    market_betas[asset_idx] * market_factor[t]
                    + sector_betas[asset_idx] * sector_factors[s_idx, t]
                    + np.random.normal(0, 0.02)  # Idiosyncratic vol 2%
                )

                data.append({
                    "ticker": ticker,
                    "date": str(current_date),
                    "return": ret,
                    "sector": f"Sector_{s_idx}",
                })

    df = pl.DataFrame(data)

    # Split train/test
    dates = sorted(df["date"].unique().to_list())
    train_dates = dates[:n_train]
    test_dates = dates[n_train:]

    df_train = df.filter(pl.col("date").is_in(train_dates))
    df_test = df.filter(pl.col("date").is_in(test_dates))

    return df_train, df_test


def optimize_minimum_variance_portfolio(cov_matrix: np.ndarray) -> np.ndarray:
    """
    Compute minimum variance portfolio weights.

    min_w  (1/2) w^T Σ w
    s.t.   1^T w = 1

    Solution: w = Σ^(-1) 1 / (1^T Σ^(-1) 1)
    """
    n = cov_matrix.shape[0]
    ones = np.ones(n)

    # Solve: Σ w = 1
    try:
        cov_inv_ones = np.linalg.solve(cov_matrix, ones)
    except np.linalg.LinAlgError:
        # If singular, use pseudo-inverse
        cov_inv_ones = np.linalg.pinv(cov_matrix) @ ones

    # Normalize: sum(w) = 1
    weights = cov_inv_ones / np.sum(cov_inv_ones)

    return weights


def compute_portfolio_returns(
    weights: np.ndarray,
    returns_df: pl.DataFrame,
) -> np.ndarray:
    """Compute portfolio returns from weights and asset returns."""
    # Convert to wide format
    returns_wide = returns_df.pivot(
        index="date",
        columns="ticker",
        values="return",
    )

    # Get returns as numpy array (T x N)
    tickers = sorted(returns_df["ticker"].unique().to_list())
    returns_matrix = returns_wide.select(tickers).to_numpy()

    # Portfolio returns: R_p = w^T R
    portfolio_returns = returns_matrix @ weights

    return portfolio_returns


def sharpe_ratio(returns: np.ndarray, annualization_factor: float = np.sqrt(252)) -> float:
    """
    Compute Sharpe ratio.

    SR = (E[R] / σ[R]) * √252
    """
    if len(returns) == 0 or np.std(returns) == 0:
        return 0.0

    return (np.mean(returns) / np.std(returns)) * annualization_factor


def compute_out_of_sample_r2(
    cov_train: np.ndarray,
    returns_test: pl.DataFrame,
) -> float:
    """
    Compute out-of-sample R² from Paper 1 (Equation in Section III).

    R²_out = 1^T S_train^(-1) S_test S_train^(-1) 1 / (1^T S_train^(-1) 1)²

    Lower is better (less prediction error).
    """
    # Get test covariance
    returns_wide = returns_test.pivot(
        index="date",
        columns="ticker",
        values="return",
    )
    tickers = sorted(returns_test["ticker"].unique().to_list())
    returns_matrix = returns_wide.select(tickers).to_numpy()

    cov_test = np.cov(returns_matrix.T)

    n = cov_train.shape[0]
    ones = np.ones(n)

    # Solve: S_train w = 1
    try:
        cov_inv_ones = np.linalg.solve(cov_train, ones)

        # S_test S_train^(-1) 1
        middle = cov_test @ cov_inv_ones

        # 1^T S_train^(-1) S_test S_train^(-1) 1
        numerator = cov_inv_ones @ middle

        # (1^T S_train^(-1) 1)²
        denominator = (np.sum(cov_inv_ones)) ** 2

        r2_out = numerator / denominator
    except np.linalg.LinAlgError:
        r2_out = np.inf

    return r2_out


def validate_model(
    name: str,
    estimator,
    train_data: pl.DataFrame,
    test_data: pl.DataFrame,
    use_long_format: bool = False,
) -> Dict:
    """
    Validate single covariance model.

    Returns metrics:
    - HHI (training weights)
    - Leverage (training weights)
    - RDI (training weights, training cov)
    - Sharpe ratio (test returns)
    - R²_out (train cov, test cov)
    """
    print(f"\n{'='*60}")
    print(f"Validating: {name}")
    print(f"{'='*60}")

    # Fit covariance on training data
    if use_long_format:
        # Sector-based models expect long format with sector column
        # TwoStep can work without sector column (discovers structure)
        if "BlockDiagonal" in name or "Stochastic" in name:
            cov_train = estimator.fit(train_data, sector_col="sector")
        else:
            cov_train = estimator.fit(train_data)
    else:
        # Baseline models expect wide format (T×N)
        train_wide = train_data.pivot(
            index="date",
            on="ticker",
            values="return",
        )
        tickers = sorted(train_data["ticker"].unique().to_list())
        train_wide = train_wide.select(tickers)
        cov_train = estimator.fit(train_wide)

    print(f"✓ Covariance fitted: {cov_train.shape}")

    # Optimize minimum variance portfolio
    weights = optimize_minimum_variance_portfolio(cov_train)
    print(f"✓ Weights optimized: sum={np.sum(weights):.4f}")

    # Compute training metrics
    hhi = herfindahl_hirschman_index(weights)
    lev = leverage(weights)
    rdi = risk_diversification_index(weights, cov_train)

    print(f"  Training Metrics:")
    print(f"    HHI (concentration): {hhi:.4f}")
    print(f"    Leverage (|w|):      {lev:.2f}")
    print(f"    RDI (diversification): {rdi:.3f}")

    # Compute test metrics
    returns_test = compute_portfolio_returns(weights, test_data)
    sharpe = sharpe_ratio(returns_test)
    r2_out = compute_out_of_sample_r2(cov_train, test_data)

    print(f"  Test Metrics:")
    print(f"    Sharpe ratio (out-of-sample): {sharpe:.3f}")
    print(f"    R²_out (prediction error):    {r2_out:.3f}")

    return {
        "name": name,
        "hhi": hhi,
        "leverage": lev,
        "rdi": rdi,
        "sharpe": sharpe,
        "r2_out": r2_out,
        "weights": weights,
        "cov_matrix": cov_train,
    }


def run_validation():
    """Run complete validation comparing all models."""
    print("="*80)
    print("PORTFOLIO PERFORMANCE VALIDATION")
    print("="*80)
    print("\nGenerating synthetic data with realistic sector structure...")

    train_data, test_data = generate_realistic_sector_data(
        n_sectors=5,
        assets_per_sector=10,
        n_train=500,
        n_test=250,
    )

    print(f"✓ Training data: {len(train_data)} observations")
    print(f"✓ Test data: {len(test_data)} observations")
    print(f"✓ Assets: {train_data['ticker'].n_unique()}")
    print(f"✓ Sectors: {train_data['sector'].n_unique()}")

    # Models to compare
    # (name, estimator, use_long_format)
    models = [
        ("1. Sample Covariance", SampleCovariance(), False),
        ("2. Ledoit-Wolf", LedoitWolfShrinkage(), False),
        ("3. BlockDiagonal (Paper 2)", BlockDiagonalCovariance(n_factors=5), True),
        ("4. TwoStep (Paper 1)", TwoStepCovariance(n_clusters=5, rmt_filter=True), True),
        ("5. StochasticBlock (Paper 3)", StochasticBlockCovariance(alpha=0.7), True),
    ]

    results = []
    for name, estimator, use_sector in models:
        result = validate_model(name, estimator, train_data, test_data, use_sector)
        results.append(result)

    # Print comparison table
    print("\n" + "="*80)
    print("COMPARISON TABLE")
    print("="*80)
    print(f"\n{'Model':<30} {'HHI':<10} {'Leverage':<10} {'RDI':<10} {'Sharpe':<10} {'R²_out':<10}")
    print("-"*80)

    for r in results:
        print(f"{r['name']:<30} {r['hhi']:<10.4f} {r['leverage']:<10.2f} {r['rdi']:<10.3f} {r['sharpe']:<10.3f} {r['r2_out']:<10.3f}")

    # Analysis
    print("\n" + "="*80)
    print("PAPER CLAIMS VS ACTUAL RESULTS")
    print("="*80)

    baseline_hhi = results[0]['hhi']  # Sample covariance
    baseline_sharpe = results[0]['sharpe']

    print("\nPaper 1 (García-Medina) Claims: TwoStep achieves 'best diversification and leverage'")
    print(f"  TwoStep HHI:      {results[3]['hhi']:.4f} vs Baseline {baseline_hhi:.4f} → {'✓ BETTER' if results[3]['hhi'] < baseline_hhi else '✗ WORSE'}")
    print(f"  TwoStep Leverage: {results[3]['leverage']:.2f} vs Baseline {results[0]['leverage']:.2f} → {'✓ LOWER' if results[3]['leverage'] < results[0]['leverage'] else '✗ HIGHER'}")

    print("\nPaper 2 (Žignić) Claims: BlockDiagonal achieves 'excellent out-of-sample Sharpe ratios'")
    print(f"  BlockDiag Sharpe: {results[2]['sharpe']:.3f} vs Baseline {baseline_sharpe:.3f} → {'✓ BETTER' if results[2]['sharpe'] > baseline_sharpe else '✗ WORSE'}")

    print("\nPaper 3 (Chen) Claims: StochasticBlock captures cross-sector correlations")
    print(f"  StochBlock Sharpe: {results[4]['sharpe']:.3f} vs Baseline {baseline_sharpe:.3f} → {'✓ BETTER' if results[4]['sharpe'] > baseline_sharpe else '✗ WORSE'}")

    print("\n" + "="*80)
    print("VALIDATION COMPLETE")
    print("="*80)

    return results


if __name__ == "__main__":
    results = run_validation()
