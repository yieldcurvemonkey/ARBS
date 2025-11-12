#!/usr/bin/env python3
# ABOUTME: Comprehensive comparison of three sector-based covariance estimators
# ABOUTME: Demonstrates usage and performance metrics for BlockDiagonal, TwoStep, and StochasticBlock
"""
Sector-Based Covariance Model Comparison

Compares three state-of-the-art sector-based covariance estimators:
1. BlockDiagonalCovariance (Žignić et al. 2024)
2. TwoStepCovariance (García-Medina et al. 2024)
3. StochasticBlockCovariance (Chen et al. 2025)

Metrics compared:
- Condition number (matrix stability)
- Sparsity (% of near-zero off-diagonal elements)
- Diversification (via eigenvalue spread)
- Computational time
"""

import numpy as np
import polars as pl
import time
from typing import Dict, Any
from datetime import date, timedelta

from Risk.Covariance.SectorBased.BlockDiagonal.BlockDiagonalCovariance import (
    BlockDiagonalCovariance,
)
from Risk.Covariance.SectorBased.TwoStep.TwoStepCovariance import TwoStepCovariance
from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
    StochasticBlockCovariance,
)


def generate_sample_data(
    n_sectors: int = 3,
    assets_per_sector: int = 5,
    n_observations: int = 252,
    seed: int = 42,
) -> pl.DataFrame:
    """
    Generate synthetic returns data with sector structure.

    Args:
        n_sectors: Number of sectors
        assets_per_sector: Assets per sector
        n_observations: Number of time observations
        seed: Random seed for reproducibility

    Returns:
        DataFrame in long format [ticker, date, return, sector]
    """
    np.random.seed(seed)

    sectors = [f"Sector_{i}" for i in range(n_sectors)]
    n_total = n_sectors * assets_per_sector

    # Generate returns with sector structure
    # Each sector has a common factor + idiosyncratic noise
    data = []
    start_date = date(2024, 1, 1)

    for t in range(n_observations):
        current_date = start_date + timedelta(days=t)

        # Sector factors (common to all assets in sector)
        sector_factors = np.random.normal(0, 0.02, n_sectors)

        for s_idx, sector in enumerate(sectors):
            for a_idx in range(assets_per_sector):
                ticker = f"{sector}_Asset_{a_idx}"

                # Return = sector factor + idiosyncratic noise
                sector_return = sector_factors[s_idx]
                idiosyncratic = np.random.normal(0, 0.01)
                total_return = sector_return + idiosyncratic

                data.append(
                    {
                        "ticker": ticker,
                        "date": str(current_date),
                        "return": total_return,
                        "sector": sector,
                    }
                )

    return pl.DataFrame(data)


def compute_metrics(cov_matrix: np.ndarray, estimator_name: str) -> Dict[str, Any]:
    """
    Compute performance metrics for covariance matrix.

    Args:
        cov_matrix: N×N covariance matrix
        estimator_name: Name of the estimator

    Returns:
        Dictionary of metrics
    """
    # Condition number (stability)
    condition_number = np.linalg.cond(cov_matrix)

    # Sparsity (% of near-zero off-diagonal elements)
    n = cov_matrix.shape[0]
    off_diag = cov_matrix[~np.eye(n, dtype=bool)]
    threshold = 1e-6
    sparsity = np.sum(np.abs(off_diag) < threshold) / len(off_diag)

    # Eigenvalue analysis
    eigenvalues = np.linalg.eigvalsh(cov_matrix)
    eigenvalue_spread = eigenvalues.max() / (eigenvalues.min() + 1e-10)
    effective_rank = np.sum(eigenvalues) ** 2 / np.sum(eigenvalues**2)

    # Frobenius norm
    frobenius_norm = np.linalg.norm(cov_matrix, "fro")

    return {
        "estimator": estimator_name,
        "condition_number": condition_number,
        "sparsity": sparsity,
        "eigenvalue_spread": eigenvalue_spread,
        "effective_rank": effective_rank,
        "frobenius_norm": frobenius_norm,
        "min_eigenvalue": eigenvalues.min(),
        "max_eigenvalue": eigenvalues.max(),
    }


def run_comparison():
    """Run comprehensive comparison of all three estimators."""
    print("=" * 80)
    print("Sector-Based Covariance Estimator Comparison")
    print("=" * 80)
    print()

    # Generate sample data
    print("Generating sample data...")
    data = generate_sample_data(n_sectors=3, assets_per_sector=5, n_observations=252)
    print(f"  - {data['ticker'].n_unique()} assets")
    print(f"  - {data['sector'].n_unique()} sectors")
    print(f"  - {len(data['date'].unique())} observations")
    print()

    results = []

    # ========================================================================
    # 1. BlockDiagonalCovariance (Žignić et al. 2024)
    # ========================================================================
    print("1. BlockDiagonalCovariance (Žignić et al. 2024)")
    print("   Paper 2: Factor model with block-diagonal residual structure")
    print("   Formula: Σ = B·Cov(F)·B^T + block_diag(Ψ₁, ..., Ψₘ)")
    print()

    estimator_bd = BlockDiagonalCovariance(
        n_factors=3,
        clustering_method="predefined",
        shrinkage_method="ledoit_wolf",
        bias_correction=True,
    )

    start_time = time.time()
    cov_bd = estimator_bd.fit(data, sector_col="sector")
    elapsed_bd = time.time() - start_time

    metrics_bd = compute_metrics(cov_bd, "BlockDiagonal")
    metrics_bd["time_seconds"] = elapsed_bd
    results.append(metrics_bd)

    print(f"   ✓ Fitted in {elapsed_bd:.3f}s")
    print(f"   - Condition number: {metrics_bd['condition_number']:.2f}")
    print(f"   - Sparsity: {metrics_bd['sparsity']:.2%}")
    print(f"   - Effective rank: {metrics_bd['effective_rank']:.1f}")
    print()

    # ========================================================================
    # 2. TwoStepCovariance (García-Medina et al. 2024)
    # ========================================================================
    print("2. TwoStepCovariance (García-Medina et al. 2024)")
    print("   Paper 1: Hierarchical clustering + RMT filtering")
    print("   Best performer for diversification and leverage metrics")
    print()

    estimator_ts = TwoStepCovariance(
        n_clusters=3, linkage_method="ward", rmt_filter=True
    )

    start_time = time.time()
    cov_ts = estimator_ts.fit(data)
    elapsed_ts = time.time() - start_time

    metrics_ts = compute_metrics(cov_ts, "TwoStep")
    metrics_ts["time_seconds"] = elapsed_ts
    results.append(metrics_ts)

    print(f"   ✓ Fitted in {elapsed_ts:.3f}s")
    print(f"   - Condition number: {metrics_ts['condition_number']:.2f}")
    print(f"   - Sparsity: {metrics_ts['sparsity']:.2%}")
    print(f"   - Effective rank: {metrics_ts['effective_rank']:.1f}")
    print()

    # ========================================================================
    # 3. StochasticBlockCovariance (Chen et al. 2025)
    # ========================================================================
    print("3. StochasticBlockCovariance (Chen et al. 2025)")
    print("   Paper 3: Allows cross-sector correlations (non-zero off-diagonal blocks)")
    print("   Formula: Σ = α·BlockDiag + (1-α)·FullCov")
    print()

    estimator_sb = StochasticBlockCovariance(
        allow_inter_block=True, alpha=0.7, discover_blocks=False, shrinkage_per_block=True
    )

    start_time = time.time()
    cov_sb = estimator_sb.fit(data, sector_col="sector")
    elapsed_sb = time.time() - start_time

    metrics_sb = compute_metrics(cov_sb, "StochasticBlock")
    metrics_sb["time_seconds"] = elapsed_sb
    results.append(metrics_sb)

    print(f"   ✓ Fitted in {elapsed_sb:.3f}s")
    print(f"   - Condition number: {metrics_sb['condition_number']:.2f}")
    print(f"   - Sparsity: {metrics_sb['sparsity']:.2%}")
    print(f"   - Effective rank: {metrics_sb['effective_rank']:.1f}")
    print()

    # ========================================================================
    # Summary Comparison
    # ========================================================================
    print("=" * 80)
    print("Summary Comparison")
    print("=" * 80)
    print()

    print(f"{'Metric':<25} {'BlockDiag':<15} {'TwoStep':<15} {'StochasticBlock':<15}")
    print("-" * 80)

    metrics_to_compare = [
        ("Condition Number", "condition_number", ".2f"),
        ("Sparsity", "sparsity", ".2%"),
        ("Eigenvalue Spread", "eigenvalue_spread", ".2f"),
        ("Effective Rank", "effective_rank", ".1f"),
        ("Computation Time (s)", "time_seconds", ".3f"),
    ]

    for metric_name, metric_key, fmt in metrics_to_compare:
        values = [f"{r[metric_key]:{fmt}}" for r in results]
        print(f"{metric_name:<25} {values[0]:<15} {values[1]:<15} {values[2]:<15}")

    print()
    print("=" * 80)
    print("Key Findings")
    print("=" * 80)
    print()
    print("1. BlockDiagonal:")
    print("   - Pure block-diagonal structure (highest sparsity)")
    print("   - Factor model separates common from idiosyncratic risk")
    print("   - Best for when sectors are truly independent")
    print()
    print("2. TwoStep:")
    print("   - Hierarchical clustering discovers structure")
    print("   - RMT filtering removes noise eigenvalues")
    print("   - Best empirical performance (per García-Medina 2024)")
    print()
    print("3. StochasticBlock:")
    print("   - Allows cross-sector correlations (α controls strength)")
    print("   - Critical for macro trading (cross-currency effects)")
    print("   - Most flexible: interpolates between block-diagonal and full cov")
    print()

    return results


if __name__ == "__main__":
    results = run_comparison()
