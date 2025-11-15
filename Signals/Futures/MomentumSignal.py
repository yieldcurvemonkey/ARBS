# ABOUTME: Momentum signal (extends BaseSignal) calculator for futures using time-series price trends
# ABOUTME: Measures rate of price change over lookback period and standardizes to Z-scores
"""
MomentumSignal - Time-series momentum for futures

Calculates momentum based on price trends over a lookback period.

Momentum Calculation:
- Simple return: (P_t - P_{t-n}) / P_{t-n}
- Log return: log(P_t / P_{t-n})
- Annualized: momentum × (252 / lookback_days)

Interpretation:
- Positive momentum (uptrend): expect continuation → long
- Negative momentum (downtrend): expect continuation → short
- Momentum = 0 (sideways): no trend signal

Expected Performance:
- IC: 0.02-0.05 (moderate skill, trend-following)
- Halflife: 20-60 days (medium frequency)
- Works best in trending markets
- Performs poorly in mean-reverting environments

Research Insights (Moskowitz et al. 2012):
- Time-series momentum strong across asset classes
- 1-12 month lookback optimal for most futures
- Significant after transaction costs
- Low correlation with cross-sectional momentum

Example:
    >>> signal = MomentumSignal(lookback_days=60)
    >>> signals = signal.calculate(['SFRZ4', 'SFRH5'], mdp, date(2024, 11, 1))
    >>> signals
    {'SFRZ4': 1.5, 'SFRH5': -0.8}  # Z-scores
"""

from datetime import date, timedelta
from typing import Optional, Any, List, Dict
import numpy as np
import polars as pl

from Signals.Base.BaseSignal import BaseSignal


class MomentumSignal(BaseSignal):
    """
    Time-series momentum signal for futures.

    Measures price trend over a lookback period and converts to
    standardized Z-score for portfolio construction.

    Attributes:
        lookback_days (int): Number of days to look back for momentum
        method (str): 'simple' or 'log' returns
        annualize (bool): If True, annualize the momentum
        business_days_per_year (int): For annualization (default: 252)

    Methods:
        calculate: Generate momentum signals for multiple instruments
        _calculate_raw_signal: Calculate momentum for single instrument

    Example:
        >>> signal = MomentumSignal(lookback_days=60)
        >>> signals = signal.calculate(['SFRZ4', 'SFRH5'], mdp, date(2024, 11, 1))
    """

    def __init__(
        self,
        name: str = "futures_momentum",
        lookback_days: int = 60,
        method: str = "simple",
        annualize: bool = False,
        standardize: bool = True,
        business_days_per_year: int = 252,
        track_history: bool = True,
    ):
        """
        Initialize MomentumSignal.

        Args:
            name: Signal name
            lookback_days: Days to look back for momentum (default: 60)
            method: 'simple' or 'log' returns (default: 'simple')
            annualize: If True, annualize momentum (default: False)
            standardize: If True, return z-scored signals (default: True)
            business_days_per_year: Trading days per year (default: 252)
            track_history: If True, store signal history (default: True)

        Example:
            Short-term momentum (3 weeks):
            >>> signal = MomentumSignal(lookback_days=21)

            Medium-term momentum (3 months):
            >>> signal = MomentumSignal(lookback_days=60)

            Long-term momentum (1 year):
            >>> signal = MomentumSignal(lookback_days=252)
        """
        super().__init__(name=name, standardize=standardize, track_history=track_history)
        self.lookback_days = lookback_days
        self.method = method
        self.annualize = annualize
        self.business_days_per_year = business_days_per_year

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Calculate raw momentum signal for a single instrument.

        Args:
            inst_data: Price history polars DataFrame with 'date' and 'price' columns
            market_data: Market data (unused for momentum)
            as_of: Calculation date

        Returns:
            Raw momentum value (return over lookback period)

        Formula:
            Simple: (P_t - P_{t-n}) / P_{t-n}
            Log: log(P_t / P_{t-n})

        Example:
            Price went from 100 to 105 over 60 days:
            >>> momentum = 0.05  # 5% gain = positive momentum
        """
        # Validate input data
        if inst_data is None or len(inst_data) == 0:
            return 0.0

        if 'price' not in inst_data.columns:
            return 0.0

        # Ensure we have date column
        if 'date' not in inst_data.columns:
            # Assume index is dates if no date column
            inst_data = inst_data.clone()
            inst_data = inst_data.with_row_index('date')

        # Convert date column to datetime if needed
        if inst_data['date'].dtype != pl.Date and inst_data['date'].dtype != pl.Datetime:
            inst_data = inst_data.clone()
            inst_data = inst_data.with_columns(
                pl.col('date').str.strptime(pl.Date, '%Y-%m-%d').cast(pl.Datetime)
            )

        # Sort by date
        inst_data = inst_data.sort('date')

        # Get current price
        current_price = inst_data['price'][-1]

        # Calculate lookback date (convert as_of to datetime for comparison)
        lookback_date = as_of - timedelta(days=self.lookback_days)

        # Find price at lookback date (or closest available)
        hist_data = inst_data.filter(pl.col('date') <= lookback_date)

        if len(hist_data) == 0:
            # Not enough history - use earliest available
            if len(inst_data) < 2:
                return 0.0
            lookback_price = inst_data['price'][0]
        else:
            lookback_price = hist_data['price'][-1]

        # Calculate momentum
        if lookback_price <= 0:
            return 0.0

        if self.method == 'log':
            momentum = np.log(current_price / lookback_price)
        else:  # 'simple'
            momentum = (current_price - lookback_price) / lookback_price

        # Annualize if requested
        if self.annualize:
            # Calculate actual days used
            end_date = inst_data['date'][-1]
            start_date = hist_data['date'][-1] if len(hist_data) > 0 else inst_data['date'][0]
            actual_days = (end_date - start_date).days
            if actual_days > 0:
                momentum = momentum * (self.business_days_per_year / actual_days)

        return float(momentum)

    def calculate(
        self,
        instruments: List[str],
        market_data: Any,
        as_of: date
    ) -> Dict[str, float]:
        """
        Calculate momentum signals for multiple instruments.

        Args:
            instruments: List of instrument identifiers
            market_data: Market data provider with get_price_history method
            as_of: Calculation date

        Returns:
            Dict mapping instrument → momentum signal (Z-score if standardize=True)

        Example:
            >>> signal = MomentumSignal(lookback_days=60)
            >>> signals = signal.calculate(['SFRZ4', 'SFRH5'], mdp, date(2024, 11, 1))
            >>> signals
            {'SFRZ4': 1.2, 'SFRH5': -0.8}  # Z-scores
        """
        raw_signals = {}

        # Calculate raw momentum for each instrument
        for instrument in instruments:
            try:
                # Get price history from market data
                lookback_date = as_of - timedelta(days=self.lookback_days + 10)  # Extra buffer
                price_history = market_data.get_price_history(
                    instrument,
                    start_date=lookback_date,
                    end_date=as_of
                )

                # Calculate raw signal
                raw_signal = self._calculate_raw_signal(
                    inst_data=price_history,
                    market_data=market_data,
                    as_of=as_of
                )

                raw_signals[instrument] = raw_signal

            except Exception as e:
                # Handle errors gracefully
                print(f"Warning: Error calculating momentum for {instrument}: {e}")
                raw_signals[instrument] = 0.0

        # Standardize to Z-scores if requested
        if self.standardize:
            signals = self._standardize_signals(raw_signals)
        else:
            signals = raw_signals

        # Track history if enabled
        if self.track_history:
            self._update_history(as_of, signals)

        self.last_generated = as_of

        return signals

    def _standardize_signals(self, raw_signals: Dict[str, float]) -> Dict[str, float]:
        """
        Standardize raw signals to Z-scores (mean=0, std=1).

        Args:
            raw_signals: Dict of raw signal values

        Returns:
            Dict of standardized Z-scores

        Formula:
            z_i = (x_i - mean(x)) / std(x)
        """
        values = list(raw_signals.keys())

        if len(values) == 0:
            return {}

        if len(values) == 1:
            # Single instrument: return 0 (no cross-sectional info)
            return {k: 0.0 for k in raw_signals.keys()}

        # Calculate mean and std
        signal_array = np.array(list(raw_signals.values()))
        mean_signal = np.mean(signal_array)
        std_signal = np.std(signal_array, ddof=1)

        if std_signal < 1e-10:
            # No variation: return zeros
            return {k: 0.0 for k in raw_signals.keys()}

        # Standardize
        standardized = {}
        for instrument, raw_value in raw_signals.items():
            z_score = (raw_value - mean_signal) / std_signal
            standardized[instrument] = float(z_score)

        return standardized

    def _update_history(self, as_of: date, signals: Dict[str, float]):
        """Update signal history for tracking."""
        if self.history is None:
            self.history = {}

        self.history[as_of] = {
            'signals': signals.copy(),
            'mean': np.mean(list(signals.values())),
            'std': np.std(list(signals.values()), ddof=1) if len(signals) > 1 else 0.0
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"MomentumSignal(name='{self.name}', "
            f"lookback={self.lookback_days}, "
            f"method='{self.method}', "
            f"standardize={self.standardize})"
        )
