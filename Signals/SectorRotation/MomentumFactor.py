# ABOUTME: Calculates momentum factors for sector rotation strategies.
# ABOUTME: Implements MOM_nM with configurable lookback periods (Yang & Shi 2023).
"""
MomentumFactor - Momentum factor calculator for sector rotation.

Implements MOM_nM formula:
    MOM_nM = Σ(past n*21 days returns) - Σ(past 0.1*n*21 days returns)

Where:
- n = number of months for cumulative return
- 21 = trading days per month (approximation)
- 0.1*n*21 = recent 10% of period (excluded to avoid short-term reversion)

Default: MOM_7M (7-month lookback, optimal from Yang & Shi 2023)
    MOM_7M achieved Sharpe ratio of 0.62 on 2017-2022 data

Mathematical Foundation:
- Momentum premium (Jegadeesh & Titman 1993): assets with strong past
  performance tend to continue performing well
- Short-term reversion exclusion: recent 1-2 months show mean reversion,
  so excluding recent 10% improves signal quality

Example:
    >>> mom_calc = MomentumFactor(lookback_months=7)
    >>> returns_df = pl.DataFrame({
    ...     "ticker": ["XLK", "XLE", ...],
    ...     "date": [...],
    ...     "return": [...]
    ... })
    >>> momentum_df = mom_calc.calculate(returns_df)
    >>> # Output: [ticker, date, momentum_factor]
"""

import polars as pl
from typing import Optional


class MomentumFactor:
    """
    Momentum factor calculator for sector rotation.

    Calculates MOM_nM = cumulative returns over n months, excluding recent 10%.
    Default: MOM_7M (optimal from paper).

    Attributes:
        lookback_months: Number of months for cumulative return (default: 7)
        exclusion_pct: Percentage of recent period to exclude (default: 0.10)
        trading_days_per_month: Trading days per month (default: 21)
    """

    def __init__(
        self,
        lookback_months: int = 7,
        exclusion_pct: float = 0.10,
        trading_days_per_month: int = 21
    ):
        """
        Initialize momentum factor calculator.

        Parameters:
            lookback_months: Number of months for cumulative return (default: 7)
                            Range: 1-12 months (tested in paper)
            exclusion_pct: Percentage of recent period to exclude (default: 0.10)
                          Excludes short-term reversion effects
            trading_days_per_month: Trading days per month (default: 21)
                                   252 trading days/year ≈ 21 days/month
        """
        if lookback_months < 1 or lookback_months > 24:
            raise ValueError("lookback_months must be between 1 and 24")

        if exclusion_pct < 0 or exclusion_pct > 0.5:
            raise ValueError("exclusion_pct must be between 0 and 0.5")

        self.lookback_months = lookback_months
        self.exclusion_pct = exclusion_pct
        self.trading_days_per_month = trading_days_per_month

        # Calculate window sizes
        self.total_lookback_days = lookback_months * trading_days_per_month
        self.exclusion_days = int(self.total_lookback_days * exclusion_pct)
        self.included_days = self.total_lookback_days - self.exclusion_days

    def calculate(
        self,
        returns_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Calculate momentum factor for each sector.

        Formula:
            MOM = sum(returns[t-lookback:t-exclusion]) - sum(returns[t-exclusion:t])
               = sum(included period) - sum(excluded period)

        Parameters:
            returns_df: DataFrame with columns [ticker, date, return]
                       Must be sorted by ticker, date

        Returns:
            DataFrame with columns [ticker, date, momentum_factor]
            One row per (ticker, date) where sufficient history exists

        Raises:
            ValueError: If insufficient history or invalid schema
        """
        # Validate input schema
        self._validate_schema(returns_df)

        # Sort by ticker and date (required for rolling operations)
        returns_df = returns_df.sort(["ticker", "date"])

        # Validate sufficient history per ticker
        self._validate_sufficient_history(returns_df)

        # Calculate rolling sums
        # 1. Total cumulative return (all lookback period)
        # 2. Recent cumulative return (exclusion period)
        # Momentum = Total - Recent

        result = (
            returns_df
            .with_columns([
                # Rolling sum over total lookback period
                pl.col("return")
                .rolling_sum(window_size=self.total_lookback_days)
                .over("ticker")
                .alias("total_cum_return"),

                # Rolling sum over exclusion period (recent returns)
                pl.col("return")
                .rolling_sum(window_size=self.exclusion_days)
                .over("ticker")
                .alias("recent_cum_return"),
            ])
            .with_columns([
                # Momentum = Total - Recent
                (pl.col("total_cum_return") - pl.col("recent_cum_return"))
                .alias("momentum_factor")
            ])
            .select(["ticker", "date", "momentum_factor"])
            # Filter out rows with null momentum (insufficient history)
            .filter(pl.col("momentum_factor").is_not_null())
        )

        return result

    def _validate_schema(self, df: pl.DataFrame) -> None:
        """
        Validate input DataFrame has required columns.

        Parameters:
            df: Input DataFrame

        Raises:
            ValueError: If required columns missing or wrong types
        """
        required_columns = ["ticker", "date", "return"]

        for col in required_columns:
            if col not in df.columns:
                raise ValueError(
                    f"Missing required column: '{col}'. "
                    f"Expected columns: {required_columns}"
                )

        # Validate types
        if df["ticker"].dtype != pl.Utf8:
            raise ValueError("Column 'ticker' must be string (Utf8)")

        if df["date"].dtype != pl.Date:
            raise ValueError("Column 'date' must be Date type")

        if not df["return"].dtype.is_float():
            raise ValueError("Column 'return' must be float type")

    def _validate_sufficient_history(self, df: pl.DataFrame) -> None:
        """
        Validate each ticker has sufficient history for momentum calculation.

        Parameters:
            df: Input DataFrame (sorted by ticker, date)

        Raises:
            ValueError: If any ticker has insufficient history
        """
        # Count observations per ticker
        ticker_counts = df.group_by("ticker").agg(
            pl.count().alias("n_obs")
        )

        # Check if any ticker has insufficient data
        insufficient = ticker_counts.filter(
            pl.col("n_obs") < self.total_lookback_days
        )

        if len(insufficient) > 0:
            tickers_list = insufficient["ticker"].to_list()
            min_obs = insufficient["n_obs"].min()

            raise ValueError(
                f"Insufficient history for momentum calculation. "
                f"Required: {self.total_lookback_days} days, "
                f"Found: {min_obs} days for tickers: {tickers_list[:5]}"
                + (" ..." if len(tickers_list) > 5 else "")
            )

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"MomentumFactor("
            f"lookback={self.lookback_months}M, "
            f"exclusion={self.exclusion_pct:.1%}, "
            f"window={self.total_lookback_days}days"
            f")"
        )
