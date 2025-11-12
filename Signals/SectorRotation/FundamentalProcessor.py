# ABOUTME: Processes and validates fundamental data for sector rotation strategies
# ABOUTME: Handles missing values, outliers, and schema validation (Yang & Shi 2023)
"""
FundamentalProcessor - Prepares fundamental data for neural network prediction.

Processes 11 fundamental factors for sector rotation:
- Valuation: PE, PB, EV/Sales, EV/EBIT, EV/EBITDA
- Income: Dividend Yield
- Margins: Gross, Operating, Profit
- Returns: ROA, ROE

Data Processing Pipeline:
1. Schema validation (11 required factors)
2. Missing value handling (forward fill for quarterly data)
3. Outlier detection (z-score > 3)
4. Outlier winsorization (cap at ±3 std)
5. Cross-sectional neutralization (via CrossSectionalNeutralizer)

From Yang & Shi (2023):
- Quarterly fundamental data from Bloomberg
- Forward fill for missing values (quarterly reports lag)
- Outlier handling critical for small sample (11 sectors × ~20 quarters)
- Cross-sectional normalization ensures comparability

Example:
    >>> processor = FundamentalProcessor()
    >>>
    >>> # Raw fundamental data (quarterly)
    >>> raw_df = pl.DataFrame({
    ...     "ticker": ["XLK", "XLE", "XLF"],
    ...     "date": [date(2023, 3, 31)] * 3,
    ...     "pe_ratio": [25.0, 15.0, None],  # Missing value
    ...     "pb_ratio": [3.5, 1.2, 200.0],    # Outlier
    ...     ...  # Other 9 factors
    ... })
    >>>
    >>> # Process: validate → fill → winsorize
    >>> processed_df = processor.process(raw_df)
    >>>
    >>> # Extract for specific quarter
    >>> q2_df = processor.get_factors_for_date(processed_df, date(2023, 6, 30))
"""

from datetime import date
from typing import List, Tuple
import polars as pl


class FundamentalProcessor:
    """
    Processes fundamental data for sector rotation strategies.

    Validates schema, handles missing values, detects and winsorizes outliers.
    Prepares data for neural network input.

    Attributes:
        factor_columns: List of 11 fundamental factor names
        outlier_threshold: Z-score threshold for outlier detection (default: 3.0)
    """

    def __init__(self, outlier_threshold: float = 3.0):
        """
        Initialize fundamental data processor.

        Parameters:
            outlier_threshold: Z-score threshold for outlier detection (default: 3.0)
                              Values with |z| > threshold are considered outliers
        """
        # 11 fundamental factors from Yang & Shi (2023) paper
        self.factor_columns = [
            "pe_ratio",          # Price-to-Earnings
            "pb_ratio",          # Price-to-Book
            "ev_sales",          # Enterprise Value / Sales
            "ev_ebit",           # Enterprise Value / EBIT
            "ev_ebitda",         # Enterprise Value / EBITDA
            "dividend_yield",    # Dividend Yield
            "gross_margin",      # Gross Margin
            "operating_margin",  # Operating Margin
            "profit_margin",     # Profit Margin
            "roa",               # Return on Assets
            "roe",               # Return on Equity
        ]

        self.outlier_threshold = outlier_threshold

    def validate_schema(self, df: pl.DataFrame) -> None:
        """
        Validate that DataFrame contains all required columns.

        Parameters:
            df: DataFrame to validate

        Raises:
            ValueError: If required columns are missing
        """
        required_columns = ["ticker", "date"] + self.factor_columns
        actual_columns = set(df.columns)
        missing_columns = [col for col in required_columns if col not in actual_columns]

        if missing_columns:
            raise ValueError(
                f"DataFrame missing required columns: {missing_columns}. "
                f"Expected columns: {required_columns}"
            )

    def handle_missing_values(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Handle missing values using forward fill within each ticker.

        Quarterly fundamental data often has gaps. Forward fill is appropriate
        because fundamentals change slowly (quarterly reports).

        Parameters:
            df: DataFrame with potential missing values

        Returns:
            DataFrame with missing values forward-filled per ticker
        """
        # Sort by ticker and date to ensure proper forward fill
        df_sorted = df.sort(["ticker", "date"])

        # Forward fill each factor column within ticker groups
        filled_df = df_sorted.with_columns([
            pl.col(factor_col).forward_fill().over("ticker")
            for factor_col in self.factor_columns
        ])

        return filled_df

    def detect_outliers(self, df: pl.DataFrame) -> List[Tuple[str, str, float, float]]:
        """
        Detect outliers using z-score method within each date.

        Outliers are values where |z-score| > threshold (default: 3.0).
        Cross-sectional detection (per date) appropriate for sector comparison.

        Parameters:
            df: DataFrame with fundamental factors

        Returns:
            List of (ticker, factor, value, z_score) tuples for outliers
        """
        outliers = []

        # Get unique dates
        dates = df["date"].unique().sort()

        for target_date in dates:
            date_df = df.filter(pl.col("date") == target_date)

            for factor_col in self.factor_columns:
                values = date_df[factor_col].to_list()
                tickers = date_df["ticker"].to_list()

                # Calculate z-scores
                mean = sum(values) / len(values)
                variance = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
                std = variance ** 0.5

                if std < 1e-10:
                    continue  # Skip if zero variance

                # Detect outliers
                for ticker, value in zip(tickers, values):
                    z_score = (value - mean) / std
                    if abs(z_score) > self.outlier_threshold:
                        outliers.append((ticker, factor_col, value, z_score))

        return outliers

    def winsorize_outliers(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Winsorize outliers by capping at ±3 standard deviations.

        Replaces extreme values with threshold values (mean ± 3*std).
        Preserves data distribution while reducing impact of extremes.

        Parameters:
            df: DataFrame with potential outliers

        Returns:
            DataFrame with outliers winsorized
        """
        result_df = df.clone()

        # Get unique dates
        dates = df["date"].unique().sort()

        for target_date in dates:
            date_mask = pl.col("date") == target_date

            for factor_col in self.factor_columns:
                # Calculate mean and std for this date
                date_df = df.filter(date_mask)
                values = date_df[factor_col].to_list()

                if len(values) < 2:
                    continue

                mean = sum(values) / len(values)
                variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
                std = variance ** 0.5

                if std < 1e-10:
                    continue

                # Calculate bounds
                lower_bound = mean - self.outlier_threshold * std
                upper_bound = mean + self.outlier_threshold * std

                # Winsorize: clip values to bounds
                result_df = result_df.with_columns([
                    pl.when(date_mask & (pl.col(factor_col) < lower_bound))
                    .then(pl.lit(lower_bound))
                    .when(date_mask & (pl.col(factor_col) > upper_bound))
                    .then(pl.lit(upper_bound))
                    .otherwise(pl.col(factor_col))
                    .alias(factor_col)
                ])

        return result_df

    def process(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Complete processing pipeline for fundamental data.

        Steps:
        1. Validate schema
        2. Handle missing values (forward fill)
        3. Winsorize outliers

        Parameters:
            df: Raw fundamental DataFrame

        Returns:
            Processed DataFrame ready for neural network or cross-sectional neutralization
        """
        # Validate schema
        self.validate_schema(df)

        # Handle missing values
        filled_df = self.handle_missing_values(df)

        # Winsorize outliers
        processed_df = self.winsorize_outliers(filled_df)

        return processed_df

    def get_factors_for_date(self, df: pl.DataFrame, target_date: date) -> pl.DataFrame:
        """
        Extract fundamental factors for a specific date.

        Parameters:
            df: Processed fundamental DataFrame
            target_date: Date to extract (typically quarter-end)

        Returns:
            DataFrame filtered to target_date

        Raises:
            ValueError: If no data for target_date
        """
        result = df.filter(pl.col("date") == target_date)

        if len(result) == 0:
            raise ValueError(
                f"No fundamental data found for date {target_date}. "
                f"Available dates: {df['date'].unique().sort().to_list()}"
            )

        return result

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"FundamentalProcessor("
            f"factors={len(self.factor_columns)}, "
            f"outlier_threshold={self.outlier_threshold}"
            f")"
        )
