# ABOUTME: Currency carry signal for fixed income strategies
# ABOUTME: Calculates carry (long_tenor_yield - short_tenor_yield) with z-score normalization

"""
CurrencyCarrySignal - Carry signal for currency rotation strategies.

Wraps carry calculation within BaseSignal framework to provide:
- Carry factor calculation (long_tenor - short_tenor)
- Cross-currency z-score standardization (currency-neutral)
- Information Coefficient (IC) tracking
- Signal history and metadata
- Butterfly carry mode (2s5s10s)

Carry is the currency equivalent of momentum in equity sectors.

Integration with Grinold-Kahn Framework:
1. Raw carry values calculated per currency-tenor
2. Cross-sectional standardization (z-scores) via BaseSignal
3. IC tracking for alpha quality monitoring
4. Scaled by AlphaGenerator: α = IC × Vol × Z

Example:
    >>> signal = CurrencyCarrySignal(long_tenor="10Y", short_tenor="2Y")
    >>>
    >>> # Generate signals for all currencies
    >>> currency_data_list = [usd_yields, eur_yields, gbp_yields, ...]
    >>> z_scores = signal.generate_batch(
    ...     inst_data_list=currency_data_list,
    ...     market_data=None,
    ...     as_of=date(2023, 12, 31)
    ... )
    >>>
    >>> # z_scores shape: (N,) for N currencies
    >>> # Properties: mean=0, std=1, ranking preserved
    >>>
    >>> # Calculate IC (forecasting skill)
    >>> forecasts = pl.Series(z_scores)
    >>> actuals = pl.Series(next_period_returns)
    >>> ic = signal.calculate_ic(forecasts, actuals)
    >>> # Target: IC > 0.05 (good), IC > 0.10 (very good)
"""

from datetime import date
from typing import Optional
import polars as pl

from Signals.Base.BaseSignal import BaseSignal


class CurrencyCarrySignal(BaseSignal):
    """
    Currency carry signal integrating yield curve analysis with BaseSignal.

    Calculates carry for currency/tenor combinations and provides z-score
    standardization, IC tracking, and signal history.

    Carry = long_tenor_yield - short_tenor_yield (simplified proxy for forward - spot)

    Attributes:
        long_tenor: Long tenor point (default: "10Y")
        short_tenor: Short tenor point (default: "2Y")
        butterfly: If True, calculate butterfly carry (default: False)
    """

    def __init__(
        self,
        long_tenor: str = "10Y",
        short_tenor: str = "2Y",
        butterfly: bool = False,
        standardize: bool = True,
        track_history: bool = True,
    ):
        """
        Initialize currency carry signal.

        Parameters:
            long_tenor: Long tenor point (e.g., "10Y", "30Y")
            short_tenor: Short tenor point (e.g., "2Y", "5Y")
            butterfly: If True, calculate butterfly carry (2s5s10s)
            standardize: If True, return z-scored alphas (default: True)
            track_history: If True, store signal generation history (default: True)
        """
        # Initialize BaseSignal
        super().__init__(
            name="currency_carry",
            standardize=standardize,
            track_history=track_history,
        )

        # Store parameters
        self.long_tenor = long_tenor
        self.short_tenor = short_tenor
        self.butterfly = butterfly

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[any],
        as_of: date,
    ) -> float:
        """
        Calculate raw carry signal for a single currency.

        This method is called by BaseSignal.generate() and generate_batch().
        It computes the carry value for one currency.

        Parameters:
            inst_data: DataFrame with columns [currency, tenor, date, yield]
                      Must contain data for both short_tenor and long_tenor
            market_data: Not used for currency carry (all data is currency-specific)
            as_of: Calculation date (must be last date in inst_data)

        Returns:
            Raw carry value (before standardization)
            Formula: Carry = long_tenor_yield - short_tenor_yield
            For butterfly: Carry = 2*belly_yield - wing1_yield - wing2_yield

        Raises:
            ValueError: If missing tenor data or invalid schema
        """
        # Filter to as_of date
        data_as_of = inst_data.filter(pl.col("date") == as_of)

        if len(data_as_of) == 0:
            raise ValueError(
                f"No data found for date {as_of}. "
                f"Ensure inst_data contains data for this date."
            )

        if self.butterfly:
            # Butterfly mode: 2*belly - wing1 - wing2
            # For 2s5s10s: 2*5Y - 2Y - 10Y
            return self._calculate_butterfly_carry(data_as_of)
        else:
            # Standard carry: long - short
            return self._calculate_spread_carry(data_as_of)

    def _calculate_spread_carry(self, data: pl.DataFrame) -> float:
        """
        Calculate spread carry: long_tenor_yield - short_tenor_yield.

        Parameters:
            data: DataFrame filtered to single date

        Returns:
            Carry value (long - short)
        """
        # Extract yields for long and short tenors
        long_data = data.filter(pl.col("tenor") == self.long_tenor)
        short_data = data.filter(pl.col("tenor") == self.short_tenor)

        if len(long_data) == 0:
            raise ValueError(
                f"Missing tenor data: {self.long_tenor}. "
                f"Available tenors: {data['tenor'].unique().to_list()}"
            )

        if len(short_data) == 0:
            raise ValueError(
                f"Missing tenor data: {self.short_tenor}. "
                f"Available tenors: {data['tenor'].unique().to_list()}"
            )

        # Get yield values
        long_yield = long_data["yield"][0]
        short_yield = short_data["yield"][0]

        # Calculate carry
        carry = long_yield - short_yield

        return carry

    def _calculate_butterfly_carry(self, data: pl.DataFrame) -> float:
        """
        Calculate butterfly carry: 2*belly - wing1 - wing2.

        For 2s5s10s butterfly:
        - wing1 = 2Y
        - belly = 5Y (self.long_tenor)
        - wing2 = 10Y

        Parameters:
            data: DataFrame filtered to single date

        Returns:
            Butterfly carry value
        """
        # Map tenors to butterfly structure
        # Assume: short_tenor=2Y, long_tenor=5Y for 2s5s10s
        # Or: short_tenor=5Y, long_tenor=10Y for 5s10s30s
        butterfly_map = {
            ("2Y", "5Y"): ("2Y", "5Y", "10Y"),  # 2s5s10s
            ("5Y", "10Y"): ("5Y", "10Y", "30Y"),  # 5s10s30s
        }

        key = (self.short_tenor, self.long_tenor)
        if key not in butterfly_map:
            raise ValueError(
                f"Unsupported butterfly combination: {key}. "
                f"Supported: 2s5s10s (2Y, 5Y), 5s10s30s (5Y, 10Y)"
            )

        wing1, belly, wing2 = butterfly_map[key]

        # Extract yields
        wing1_data = data.filter(pl.col("tenor") == wing1)
        belly_data = data.filter(pl.col("tenor") == belly)
        wing2_data = data.filter(pl.col("tenor") == wing2)

        if len(wing1_data) == 0 or len(belly_data) == 0 or len(wing2_data) == 0:
            missing = []
            if len(wing1_data) == 0:
                missing.append(wing1)
            if len(belly_data) == 0:
                missing.append(belly)
            if len(wing2_data) == 0:
                missing.append(wing2)

            raise ValueError(
                f"Missing tenor data for butterfly: {', '.join(missing)}. "
                f"Available tenors: {data['tenor'].unique().to_list()}"
            )

        # Get yield values
        wing1_yield = wing1_data["yield"][0]
        belly_yield = belly_data["yield"][0]
        wing2_yield = wing2_data["yield"][0]

        # Calculate butterfly carry
        butterfly_carry = 2 * belly_yield - wing1_yield - wing2_yield

        return butterfly_carry

    def __repr__(self) -> str:
        """Return string representation."""
        mode = "butterfly" if self.butterfly else "spread"
        return (
            f"CurrencyCarrySignal("
            f"name='{self.name}', "
            f"mode={mode}, "
            f"tenors={self.short_tenor}-{self.long_tenor}, "
            f"standardize={self.standardize}"
            f")"
        )
