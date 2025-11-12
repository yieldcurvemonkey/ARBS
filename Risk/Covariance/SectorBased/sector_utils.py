# ABOUTME: Shared utilities for sector-based covariance estimators
# ABOUTME: Common functions for all three approaches (BlockDiagonal, TwoStep, StochasticBlock)
"""
Sector-Based Covariance Utilities

Common utilities shared by all sector-based covariance estimators:
- Data format conversion (long → wide)
- Sector extraction and validation
- Common abstractions

All three approaches (BlockDiagonal, TwoStep, StochasticBlock) use these utilities.
"""

import polars as pl
import numpy as np
from typing import Tuple, Dict, List, Optional


def validate_sector_data(returns: pl.DataFrame, sector_col: str = "sector") -> None:
    """
    Validate that DataFrame has required columns for sector-based estimation.

    Args:
        returns: DataFrame with columns [ticker, date, return, sector]
        sector_col: Name of sector column

    Raises:
        ValueError: If required columns missing or data invalid
    """
    required_cols = ["ticker", "date", "return", sector_col]
    missing = [col for col in required_cols if col not in returns.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Check for null sectors
    null_sectors = returns.filter(pl.col(sector_col).is_null())
    if len(null_sectors) > 0:
        raise ValueError(f"Found {len(null_sectors)} rows with null sector")

    # Check for null returns
    null_returns = returns.filter(pl.col("return").is_null())
    if len(null_returns) > 0:
        raise ValueError(f"Found {len(null_returns)} rows with null return")


def long_to_wide(
    returns: pl.DataFrame,
    pivot_col: str = "ticker",
    value_col: str = "return",
) -> Tuple[pl.DataFrame, List[str]]:
    """
    Convert long format DataFrame to wide format for covariance estimation.

    Args:
        returns: DataFrame in long format [ticker, date, return, ...]
        pivot_col: Column to pivot (usually "ticker")
        value_col: Value column (usually "return")

    Returns:
        Tuple of (wide_df, tickers)
        - wide_df: DataFrame with dates as rows, tickers as columns
        - tickers: List of ticker names (column order)
    """
    # Pivot to wide format
    wide = returns.pivot(
        index="date",
        columns=pivot_col,
        values=value_col,
    ).sort("date")

    # Get ticker names (all columns except 'date')
    tickers = [col for col in wide.columns if col != "date"]

    # Drop date column for covariance calculation
    wide_returns = wide.select(tickers)

    return wide_returns, tickers


def extract_sector_mapping(
    returns: pl.DataFrame,
    sector_col: str = "sector",
) -> Dict[str, str]:
    """
    Extract ticker → sector mapping from DataFrame.

    Args:
        returns: DataFrame with [ticker, sector] columns
        sector_col: Name of sector column

    Returns:
        Dictionary mapping ticker → sector
    """
    # Get unique ticker-sector pairs
    sector_map = (
        returns
        .select(["ticker", sector_col])
        .unique()
        .to_dict(as_series=False)
    )

    tickers = sector_map["ticker"]
    sectors = sector_map[sector_col]

    return dict(zip(tickers, sectors))


def get_sectors_list(
    returns: pl.DataFrame,
    sector_col: str = "sector",
) -> List[str]:
    """
    Get list of unique sectors in dataset.

    Args:
        returns: DataFrame with sector column
        sector_col: Name of sector column

    Returns:
        List of unique sector names (sorted)
    """
    sectors = returns[sector_col].unique().sort().to_list()
    return sectors


def group_tickers_by_sector(
    ticker_sector_map: Dict[str, str],
) -> Dict[str, List[str]]:
    """
    Group tickers by their sector.

    Args:
        ticker_sector_map: Dictionary mapping ticker → sector

    Returns:
        Dictionary mapping sector → list of tickers
    """
    sector_groups = {}
    for ticker, sector in ticker_sector_map.items():
        if sector not in sector_groups:
            sector_groups[sector] = []
        sector_groups[sector].append(ticker)

    return sector_groups


def create_block_diagonal_matrix(
    blocks: Dict[str, np.ndarray],
    ticker_order: List[str],
    ticker_sector_map: Dict[str, str],
) -> np.ndarray:
    """
    Construct block-diagonal matrix from sector blocks.

    Args:
        blocks: Dictionary mapping sector → covariance block (n_i × n_i)
        ticker_order: Global ticker ordering
        ticker_sector_map: Mapping of ticker → sector

    Returns:
        Block-diagonal covariance matrix (N × N)
    """
    n = len(ticker_order)
    cov_matrix = np.zeros((n, n))

    # Group tickers by sector
    sector_groups = group_tickers_by_sector(ticker_sector_map)

    # Get indices for each ticker
    ticker_to_idx = {ticker: i for i, ticker in enumerate(ticker_order)}

    # Fill in each block
    for sector, tickers in sector_groups.items():
        if sector not in blocks:
            raise ValueError(f"Missing covariance block for sector: {sector}")

        # Get indices for this sector's tickers
        indices = [ticker_to_idx[t] for t in tickers]

        # Get block matrix
        block = blocks[sector]

        # Fill in block-diagonal position
        for i, idx_i in enumerate(indices):
            for j, idx_j in enumerate(indices):
                cov_matrix[idx_i, idx_j] = block[i, j]

    return cov_matrix
