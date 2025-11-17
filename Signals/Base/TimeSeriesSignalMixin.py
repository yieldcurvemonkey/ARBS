# ABOUTME: Mixin providing common time-series signal functionality (calculate, standardize, history tracking)
# ABOUTME: Used by MomentumSignal, MeanReversionSignal, and other time-series signals to eliminate duplication

from datetime import date, timedelta
from typing import Dict, List, Any, Optional, Union, Tuple
import logging
import numpy as np
import polars as pl


class TimeSeriesSignalMixin:
    """
    Mixin for common time-series signal functionality.

    Provides:
    - calculate(): Batch signal generation for multiple instruments
    - _standardize_signals(): Z-score normalization (mean=0, std=1)
    - _update_history(): Signal history tracking

    Requirements:
    - Must be mixed with BaseSignal
    - Subclass must implement _calculate_raw_signal()
    - Subclass must have attributes: standardize, track_history, name
    """

    def calculate(
        self,
        instruments: List[str],
        market_data: Any,
        as_of: date,
    ) -> Dict[str, float]:
        """
        Calculate signals for multiple instruments.

        Delegates to BaseSignal.generate_batch() to reuse existing infrastructure.

        Args:
            instruments: List of instrument identifiers
            market_data: Market data provider with get_price_history method
            as_of: Calculation date

        Returns:
            Dict mapping instrument → signal (Z-score if standardize=True, raw if False)
            Note: Failed instruments are excluded from the result
        """
        # Enforce contract - mixin requires these attributes
        required_attrs = ['lookback_days', 'standardize', 'track_history', '_calculate_raw_signal']
        missing = [attr for attr in required_attrs if not hasattr(self, attr)]

        if missing:
            raise TypeError(
                f"{self.__class__.__name__} must define {missing} to use TimeSeriesSignalMixin. "
                f"Ensure your class extends BaseSignal and defines lookback_days in __init__."
            )

        # Fetch price history for all instruments
        inst_data_list = []
        failed_instruments = []
        lookback_days = self.lookback_days

        for instrument in instruments:
            try:
                lookback_date = as_of - timedelta(days=lookback_days + 10)
                price_history = market_data.get_price_history(
                    instrument,
                    start_date=lookback_date,
                    end_date=as_of
                )
                inst_data_list.append(price_history)
            except Exception as e:
                logging.getLogger(__name__).warning(
                    "Excluding instrument from universe",
                    extra={'instrument': instrument, 'error': str(e)}
                )
                failed_instruments.append(instrument)

        # Only process instruments that succeeded
        successful_instruments = [i for i in instruments if i not in failed_instruments]

        if not successful_instruments:
            return {}

        # Delegate to BaseSignal.generate_batch()
        signals_array = self.generate_batch(inst_data_list, market_data, as_of)

        # Convert array to dict
        return {inst: float(sig) for inst, sig in zip(successful_instruments, signals_array)}

    def _standardize_signals(self, raw_signals: Dict[str, float]) -> Dict[str, float]:
        """
        Standardize raw signals to Z-scores (mean=0, std=1).

        Cross-sectional standardization: Compare each instrument's signal
        to the mean signal across all instruments.

        Args:
            raw_signals: Dict of raw signal values

        Returns:
            Dict of standardized Z-scores

        Formula:
            z_i = (x_i - mean(x)) / std(x)

        Edge cases:
            - Empty dict: return {}
            - Single instrument: return {instrument: 0.0}
            - No variation (std=0): return {instrument: 0.0 for all}
        """
        if len(raw_signals) == 0:
            return {}

        if len(raw_signals) == 1:
            # Single instrument: no cross-sectional info → return 0
            return {k: 0.0 for k in raw_signals.keys()}

        # Calculate mean and std across instruments
        signal_array = np.array(list(raw_signals.values()))
        mean_signal = np.mean(signal_array)
        std_signal = np.std(signal_array, ddof=1)

        if std_signal < 1e-10:
            # No variation: all signals identical → return zeros
            return {k: 0.0 for k in raw_signals.keys()}

        # Standardize each signal
        standardized = {}
        for instrument, raw_value in raw_signals.items():
            z_score = (raw_value - mean_signal) / std_signal
            standardized[instrument] = float(z_score)

        return standardized

    def _update_history(self, as_of: date, signals: Dict[str, float]) -> None:
        """
        Update signal history for tracking.

        Stores:
        - as_of date
        - signals dict
        - cross-sectional mean
        - cross-sectional std

        Args:
            as_of: Date of signal generation
            signals: Dict of instrument → signal
        """
        if self.history is None:
            self.history = {}

        self.history[as_of] = {
            'signals': signals.copy(),
            'mean': np.mean(list(signals.values())),
            'std': np.std(list(signals.values()), ddof=1) if len(signals) > 1 else 0.0
        }

    def _get_price_window(
        self,
        inst_data: pl.DataFrame,
        as_of: date,
        lookback_days: int,
        return_series: bool = False,
        market_data: Optional[Any] = None
    ) -> Union[Tuple[float, float, int], Tuple[float, np.ndarray, int]]:
        """
        Extract price window for time-series signal calculations.

        Consolidates common logic for:
        - DataFrame validation (None, empty, missing columns)
        - Date column handling (string → datetime conversion)
        - DataFrame sorting by date
        - Price window extraction

        Args:
            inst_data: Price history DataFrame with 'date' and 'price' columns
            as_of: Calculation date
            lookback_days: Number of days to look back
            return_series: If True, return full price series; if False, return endpoints
            market_data: Market data provider (unused, for signature compatibility)

        Returns:
            If return_series=False (momentum use case):
                (current_price, lookback_price, actual_days)
                - current_price: Most recent price
                - lookback_price: Price at start of lookback window
                - actual_days: Actual calendar days in window

            If return_series=True (mean reversion use case):
                (current_price, past_prices, actual_days)
                - current_price: Most recent price
                - past_prices: NumPy array of past prices (excluding current)
                - actual_days: Actual calendar days in window

        Raises:
            ValueError: If data is insufficient or invalid

        Edge Cases:
            - Insufficient history: Uses all available data
            - Missing date column: Raises ValueError
            - Zero/negative prices: Handled by caller
            - Short history (< 2 points): Raises ValueError for mean reversion

        Example (Momentum):
            >>> current, lookback, days = self._get_price_window(
            ...     inst_data, date(2024, 11, 1), lookback_days=60
            ... )
            >>> momentum = (current - lookback) / lookback

        Example (Mean Reversion):
            >>> current, past_prices, days = self._get_price_window(
            ...     inst_data, date(2024, 11, 1), lookback_days=20, return_series=True
            ... )
            >>> mean = np.mean(past_prices)
            >>> std = np.std(past_prices, ddof=1)
            >>> signal = -1.0 * (current - mean) / std
        """
        # Validate input data
        if inst_data is None or len(inst_data) == 0:
            raise ValueError("inst_data is None or empty")

        if 'price' not in inst_data.columns:
            raise ValueError("inst_data missing 'price' column")

        # Ensure we have date column
        if 'date' not in inst_data.columns:
            if return_series:
                # Mean reversion needs proper dates
                raise ValueError("inst_data missing 'date' column")
            else:
                # Momentum can work with indexed data
                inst_data = inst_data.clone()
                inst_data = inst_data.with_row_index('date')

        # Convert date column to datetime if needed
        date_dtype = inst_data['date'].dtype
        if date_dtype not in [pl.Date, pl.Datetime, pl.Datetime('us'), pl.Datetime('ms'), pl.Datetime('ns')]:
            inst_data = inst_data.with_columns(
                pl.col('date').str.strptime(pl.Datetime, '%Y-%m-%d')
            )

        # Sort by date
        inst_data = inst_data.sort('date')

        # Get current price
        current_price = float(inst_data['price'][-1])

        # Calculate lookback date
        lookback_date = as_of - timedelta(days=lookback_days)

        if return_series:
            # Mean reversion use case: return full price series in window
            window_data = inst_data.filter(pl.col('date') >= lookback_date)

            if len(window_data) < 2:
                raise ValueError("Insufficient history for mean reversion (need at least 2 points)")

            # Extract past prices (excluding current)
            past_prices = window_data['price'].to_numpy()[:-1]

            if len(past_prices) < 1:
                raise ValueError("Insufficient past prices (need at least 1)")

            # Calculate actual days
            end_date = window_data['date'][-1]
            start_date = window_data['date'][0]
            if hasattr(end_date, 'date'):
                end_date = end_date.date()
            if hasattr(start_date, 'date'):
                start_date = start_date.date()
            actual_days = (end_date - start_date).days

            return (current_price, past_prices, actual_days)

        else:
            # Momentum use case: return current and lookback prices
            # Find price at or before lookback date
            hist_data = inst_data.filter(pl.col('date') <= lookback_date)

            if len(hist_data) == 0:
                # Not enough history - use earliest available
                if len(inst_data) < 2:
                    raise ValueError("Insufficient history for momentum (need at least 2 points)")
                lookback_price = float(inst_data['price'][0])
                start_date = inst_data['date'][0]
            else:
                lookback_price = float(hist_data['price'][-1])
                start_date = hist_data['date'][-1]

            # Calculate actual days
            end_date = inst_data['date'][-1]
            if hasattr(end_date, 'date'):
                end_date = end_date.date()
            if hasattr(start_date, 'date'):
                start_date = start_date.date()
            actual_days = (end_date - start_date).days

            return (current_price, lookback_price, actual_days)
