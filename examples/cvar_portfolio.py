# ABOUTME: CVaR-constrained portfolio optimization example
# ABOUTME: Demonstrates tail risk reduction through CVaR constraints vs. unconstrained
"""
CVaR Portfolio Optimization Example

Demonstrates Conditional Value-at-Risk (CVaR) constraints for tail risk control.

Flow:
1. Load equity returns (synthetic with some tail risk)
2. Generate signals using simple momentum
3. Optimize with CVaR constraint (α=0.05, limit=0.05)
4. Compare CVaR-constrained vs. unconstrained:
   - CVaR (empirical tail risk)
   - Max drawdown
   - Sharpe ratio
   - 95th percentile loss
5. Show tradeoff: Sharpe vs tail risk

Theory:
    CVaR_α = expected loss beyond α-percentile
    e.g., CVaR_0.05 = average of worst 5% days

Interpretation:
    CVaR limit = 0.05 means max expected tail loss is 5% per day
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import polars as pl
from scipy.stats import t as t_distribution

# Suppress warnings
import warnings
warnings.filterwarnings('ignore')


def generate_returns_with_tail_risk(n_assets: int = 10, n_periods: int = 252, seed: int = 42):
    """
    Generate synthetic equity returns with some tail risk.

    Uses t-distribution (fat tails) instead of normal to create realistic
    scenario where CVaR constraints matter.

    Args:
        n_assets: Number of assets
        n_periods: Number of time periods (days)
        seed: Random seed

    Returns:
        returns: np.ndarray (n_periods, n_assets)
    """
    np.random.seed(seed)

    # Generate returns with fat tails (t-distribution, df=4)
    dof = 4  # Degrees of freedom
    returns = np.zeros((n_periods, n_assets))
    for i in range(n_assets):
        # t-distribution returns scaled to ~15% annualized vol
        returns[:, i] = t_distribution.rvs(dof, size=n_periods) * 0.01

    return returns


def calculate_momentum_signals(returns: np.ndarray, lookback: int = 20) -> np.ndarray:
    """
    Calculate simple momentum signals.

    Signal = mean return over lookback period (z-scored).

    Args:
        returns: np.ndarray (n_periods, n_assets)
        lookback: Lookback window

    Returns:
        signals: np.ndarray (n_assets,) z-scored
    """
    mean_returns = np.mean(returns[-lookback:, :], axis=0)
    std_returns = np.std(returns[-lookback:, :], axis=0) + 1e-6
    signals = (mean_returns - np.mean(mean_returns)) / std_returns
    return signals


def calculate_empirical_metrics(returns: np.ndarray, weights: np.ndarray) -> dict:
    """
    Calculate portfolio metrics.

    Args:
        returns: np.ndarray (n_periods, n_assets)
        weights: np.ndarray (n_assets,)

    Returns:
        dict with metrics
    """
    portfolio_returns = returns @ weights

    # CVaR (95th percentile)
    losses = -portfolio_returns
    var_95 = np.quantile(losses, 0.95)
    cvar_95 = np.mean(losses[losses >= var_95])

    # VaR (95th percentile)
    var_95_value = np.quantile(portfolio_returns, 0.05)

    # Sharpe ratio (annualized, assuming 252 trading days)
    sharpe = (np.mean(portfolio_returns) * 252) / (np.std(portfolio_returns) * np.sqrt(252) + 1e-6)

    # Max drawdown
    cumsum = np.cumprod(1 + portfolio_returns)
    running_max = np.maximum.accumulate(cumsum)
    drawdown = (cumsum - running_max) / running_max
    max_dd = np.min(drawdown)

    # 95th percentile loss
    pct_95_loss = np.percentile(portfolio_returns, 5)

    # Total return
    total_return = np.prod(1 + portfolio_returns) - 1

    return {
        'cvar_95': cvar_95,
        'var_95': -var_95_value,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'pct_95_loss': pct_95_loss,
        'total_return': total_return,
        'avg_daily_return': np.mean(portfolio_returns),
        'volatility': np.std(portfolio_returns),
    }


def main():
    """Run CVaR portfolio optimization example."""
    print("=" * 80)
    print("CVaR PORTFOLIO OPTIMIZATION EXAMPLE")
    print("=" * 80)
    print()

    # Step 1: Generate synthetic returns
    print("Step 1: Generating synthetic returns with fat tails...")
    n_assets = 10
    n_periods = 252
    returns = generate_returns_with_tail_risk(n_assets, n_periods, seed=42)
    print(f"  Generated {n_periods} periods × {n_assets} assets")
    print(f"  Annualized volatility: {np.std(returns) * np.sqrt(252):.2%}")
    print()

    # Step 2: Calculate signals
    print("Step 2: Calculating momentum signals...")
    signals = calculate_momentum_signals(returns, lookback=20)
    print(f"  Signals: {signals}")
    print()

    # Step 3: Create covariance matrix
    print("Step 3: Computing covariance matrix...")
    cov_matrix = np.cov(returns.T)
    print(f"  Covariance shape: {cov_matrix.shape}")
    print()

    # Step 4: Optimize unconstrained
    print("Step 4: Optimizing unconstrained portfolio...")
    from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

    alphas_series = pl.Series('alphas', signals.tolist())
    cov_df = pl.DataFrame(cov_matrix)

    opt_unconstrained = MeanVarianceOptimizer(
        risk_aversion=1.0,
        long_only=True,
        position_limit=0.3,
    )
    weights_unconstrained = opt_unconstrained.optimize(alphas_series, cov_df)
    weights_unconstrained_array = np.array(list(weights_unconstrained.values()))

    print(f"  Weights: {weights_unconstrained}")
    print(f"  Sum: {sum(weights_unconstrained.values()):.4f}")
    print(f"  Max position: {max(weights_unconstrained.values()):.4f}")
    print()

    # Step 5: Optimize with CVaR constraint
    print("Step 5: Optimizing with CVaR constraint (α=0.05, limit=0.05)...")
    from Optimizer.CVaRMeanVarianceOptimizer import CVaRMeanVarianceOptimizer

    opt_cvar = CVaRMeanVarianceOptimizer(
        risk_aversion=1.0,
        long_only=True,
        position_limit=0.3,
        cvar_alpha=0.05,
        cvar_limit=0.05,
    )

    # Pass returns for CVaR calculation
    weights_cvar = opt_cvar.optimize(alphas_series, cov_df, returns=returns)
    weights_cvar_array = np.array(list(weights_cvar.values()))

    print(f"  Weights: {weights_cvar}")
    print(f"  Sum: {sum(weights_cvar.values()):.4f}")
    print(f"  Max position: {max(weights_cvar.values()):.4f}")
    print()

    # Step 6: Calculate metrics for unconstrained
    print("Step 6: Calculating portfolio metrics...")
    print()

    metrics_unconstrained = calculate_empirical_metrics(returns, weights_unconstrained_array)
    metrics_cvar = calculate_empirical_metrics(returns, weights_cvar_array)

    print("UNCONSTRAINED PORTFOLIO:")
    print(f"  CVaR (95%):        {metrics_unconstrained['cvar_95']:>8.4f}")
    print(f"  VaR (95%):         {metrics_unconstrained['var_95']:>8.4f}")
    print(f"  Sharpe ratio:      {metrics_unconstrained['sharpe']:>8.4f}")
    print(f"  Max drawdown:      {metrics_unconstrained['max_drawdown']:>8.4f}")
    print(f"  95th %ile loss:    {metrics_unconstrained['pct_95_loss']:>8.4f}")
    print(f"  Total return:      {metrics_unconstrained['total_return']:>8.4f}")
    print(f"  Avg daily return:  {metrics_unconstrained['avg_daily_return']:>8.6f}")
    print(f"  Volatility:        {metrics_unconstrained['volatility']:>8.4f}")
    print()

    print("CVaR-CONSTRAINED PORTFOLIO (α=0.05, limit=0.05):")
    print(f"  CVaR (95%):        {metrics_cvar['cvar_95']:>8.4f}")
    print(f"  VaR (95%):         {metrics_cvar['var_95']:>8.4f}")
    print(f"  Sharpe ratio:      {metrics_cvar['sharpe']:>8.4f}")
    print(f"  Max drawdown:      {metrics_cvar['max_drawdown']:>8.4f}")
    print(f"  95th %ile loss:    {metrics_cvar['pct_95_loss']:>8.4f}")
    print(f"  Total return:      {metrics_cvar['total_return']:>8.4f}")
    print(f"  Avg daily return:  {metrics_cvar['avg_daily_return']:>8.6f}")
    print(f"  Volatility:        {metrics_cvar['volatility']:>8.4f}")
    print()

    # Step 7: Show improvements
    print("IMPROVEMENTS (CVaR vs Unconstrained):")
    print(f"  CVaR reduction:     {(1 - metrics_cvar['cvar_95']/metrics_unconstrained['cvar_95'])*100:>7.2f}%")
    print(f"  VaR reduction:      {(1 - metrics_cvar['var_95']/metrics_unconstrained['var_95'])*100:>7.2f}%")
    print(f"  Max DD improvement: {(1 - metrics_cvar['max_drawdown']/metrics_unconstrained['max_drawdown'])*100:>7.2f}%")
    print(f"  95th %ile improve:  {(1 - metrics_cvar['pct_95_loss']/metrics_unconstrained['pct_95_loss'])*100:>7.2f}%")
    print()

    # Step 8: Show Sharpe tradeoff
    print("RISK-RETURN TRADEOFF:")
    sharpe_diff = metrics_cvar['sharpe'] - metrics_unconstrained['sharpe']
    total_return_diff = metrics_cvar['total_return'] - metrics_unconstrained['total_return']
    print(f"  Sharpe ratio change:     {sharpe_diff:+.4f}")
    print(f"  Total return change:     {total_return_diff:+.4f}")
    print()

    if sharpe_diff < 0:
        print("  INTERPRETATION: CVaR constraint reduces Sharpe ratio but improves tail risk.")
    else:
        print("  INTERPRETATION: CVaR constraint improves both Sharpe and tail risk!")
    print()

    # Step 9: Create comparison table
    print("=" * 80)
    print("SUMMARY COMPARISON TABLE")
    print("=" * 80)
    print()
    print(f"{'Metric':<20} {'Unconstrained':>15} {'CVaR Limited':>15} {'Improvement':>15}")
    print("-" * 65)
    print(f"{'CVaR (95%)':<20} {metrics_unconstrained['cvar_95']:>15.4f} {metrics_cvar['cvar_95']:>15.4f} {(metrics_unconstrained['cvar_95']-metrics_cvar['cvar_95']):>15.4f}")
    print(f"{'VaR (95%)':<20} {metrics_unconstrained['var_95']:>15.4f} {metrics_cvar['var_95']:>15.4f} {(metrics_unconstrained['var_95']-metrics_cvar['var_95']):>15.4f}")
    print(f"{'Max Drawdown':<20} {metrics_unconstrained['max_drawdown']:>15.4f} {metrics_cvar['max_drawdown']:>15.4f} {(metrics_unconstrained['max_drawdown']-metrics_cvar['max_drawdown']):>15.4f}")
    print(f"{'Sharpe Ratio':<20} {metrics_unconstrained['sharpe']:>15.4f} {metrics_cvar['sharpe']:>15.4f} {(metrics_cvar['sharpe']-metrics_unconstrained['sharpe']):>15.4f}")
    print(f"{'Total Return':<20} {metrics_unconstrained['total_return']:>15.4f} {metrics_cvar['total_return']:>15.4f} {(metrics_cvar['total_return']-metrics_unconstrained['total_return']):>15.4f}")
    print()

    print("=" * 80)
    print("KEY INSIGHTS")
    print("=" * 80)
    print()
    print("1. CVaR Constraint Binding:")
    print(f"   - CVaR (unconstrained): {metrics_unconstrained['cvar_95']:.4f}")
    print(f"   - CVaR (limit):         {0.05:.4f}")
    print(f"   - CVaR (constrained):   {metrics_cvar['cvar_95']:.4f}")
    if metrics_cvar['cvar_95'] <= 0.05 + 0.001:
        print("   ✓ Constraint is binding (CVaR ≈ limit)")
    else:
        print("   ✗ Constraint not binding (CVaR > limit)")
    print()

    print("2. Tail Risk Reduction:")
    cvar_reduction = (1 - metrics_cvar['cvar_95']/metrics_unconstrained['cvar_95'])*100
    print(f"   - CVaR reduced by {cvar_reduction:.1f}%")
    print(f"   - Max drawdown improved by {(1 - metrics_cvar['max_drawdown']/metrics_unconstrained['max_drawdown'])*100:.1f}%")
    print()

    print("3. Performance Tradeoff:")
    print(f"   - Sharpe ratio: {metrics_unconstrained['sharpe']:.4f} → {metrics_cvar['sharpe']:.4f}")
    print(f"   - Total return: {metrics_unconstrained['total_return']:.4f} → {metrics_cvar['total_return']:.4f}")
    print()

    print("4. Practical Application:")
    print("   - Use CVaR constraints for conservative portfolios (pensions, insurance)")
    print("   - Trades off small Sharpe reduction for significant tail risk reduction")
    print("   - Particularly valuable during market stress (when tail events matter most)")
    print()


if __name__ == "__main__":
    main()
