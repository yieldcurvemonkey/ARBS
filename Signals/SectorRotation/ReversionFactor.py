# ABOUTME: Calculates short-term reversion factors for sector rotation.
# ABOUTME: Implements REV_nD contrarian signals (Yang & Shi 2023).
"""
ReversionFactor - Short-term reversion factor calculator for sector rotation.

Implements REV_nD formula:
    REV_nD = -Σ(past n days returns)

Where:
- n = number of days for cumulative return
- Negative sign = contrarian logic (bet against recent trends)

Default: REV_30D (30-day lookback, optimal from Yang & Shi 2023)
    REV_30D achieved Sharpe ratio of 0.87 on 2002-2022 data

Mathematical Foundation:
- Mean reversion: asset prices tend to revert to mean in short term
- Contrarian strategy: bet against recent winners, bet on recent losers
- Short-term reversion complements medium-term momentum

Contrarian Logic:
    Recent winner (positive cumulative return):
        REV = -(+0.20) = -0.20 → bearish signal (expect pullback)

    Recent loser (negative cumulative return):
        REV = -(-0.15) = +0.15 → bullish signal (expect recovery)

Example:
    >>> rev_calc = ReversionFactor(lookback_days=30)
    >>> returns_df = pl.DataFrame({
    ...     "ticker": ["XLK", "XLE", ...],
    ...     "date": [...],
    ...     "return": [...]
    ... })
    >>> reversion_df = rev_calc.calculate(returns_df)
    >>> # Output: [ticker, date, reversion_factor]
    >>> # Winners get negative signals, losers get positive signals
"""

import polars as pl
from typing import Optional


class ReversionFactor:
    """
    Short-term reversion factor calculator for sector rotation.

    Calculates REV_nD = negative cumulative returns over n days.
    Default: REV_30D (optimal from paper).

    Attributes:
        lookback_days: Number of days for cumulative return (default: 30)
    """

    def __init__(self, lookback_days: int = 30):
        """
        Initialize reversion factor calculator.

        Parameters:
            lookback_days: Number of days for cumulative return (default: 30)
                          Range: 5-55 days (tested in paper)
                          Optimal: 30 days (Sharpe 0.87)
        """
        if lookback_days < 1 or lookback_days > 100:
            raise ValueError("lookback_days must be between 1 and 100")

        self.lookback_days = lookback_days

    def calculate(
        self,
        returns_df: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Calculate reversion factor for each sector.

        Formula:
            REV_nD = -sum(returns[t-n:t])

        Contrarian Logic:
            - Positive cumulative return → negative REV (bearish on winner)
            - Negative cumulative return → positive REV (bullish on loser)

        Parameters:
            returns_df: DataFrame with columns [ticker, date, return]
                       Must be sorted by ticker, date

        Returns:
            DataFrame with columns [ticker, date, reversion_factor]
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

        # Calculate rolling sum and negate for contrarian signal
        result = (
            returns_df
            .with_columns([
                # Rolling sum over lookback period
                pl.col("return")
                .rolling_sum(window_size=self.lookback_days)
                .over("ticker")
                .alias("cumulative_return"),
            ])
            .with_columns([
                # Reversion = -cumulative_return (contrarian)
                (-pl.col("cumulative_return"))
                .alias("reversion_factor")
            ])
            .select(["ticker", "date", "reversion_factor"])
            # Filter out rows with null reversion (insufficient history)
            .filter(pl.col("reversion_factor").is_not_null())
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
        Validate each ticker has sufficient history for reversion calculation.

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
            pl.col("n_obs") < self.lookback_days
        )

        if len(insufficient) > 0:
            tickers_list = insufficient["ticker"].to_list()
            min_obs = insufficient["n_obs"].min()

            raise ValueError(
                f"Insufficient history for reversion calculation. "
                f"Required: {self.lookback_days} days, "
                f"Found: {min_obs} days for tickers: {tickers_list[:5]}"
                + (" ..." if len(tickers_list) > 5 else "")
            )

    def __repr__(self) -> str:
        """Return string representation."""
        return f"ReversionFactor(lookback={self.lookback_days}D)"
