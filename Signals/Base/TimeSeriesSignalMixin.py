# ABOUTME: Mixin providing common time-series signal functionality (calculate, standardize, history tracking)
# ABOUTME: Used by MomentumSignal, MeanReversionSignal, and other time-series signals to eliminate duplication

from datetime import date, timedelta
from typing import Dict, List, Any, Optional
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

        Pattern:
        1. Loop over instruments
        2. Fetch price history from market_data
        3. Call _calculate_raw_signal() for each instrument
        4. Handle errors gracefully
        5. Standardize to Z-scores if requested
        6. Track history if enabled

        Args:
            instruments: List of instrument identifiers
            market_data: Market data provider with get_price_history method
            as_of: Calculation date

        Returns:
            Dict mapping instrument → signal (Z-score if standardize=True, raw if False)
        """
        raw_signals = {}

        # Get lookback for price history (subclass must define self.lookback_days)
        lookback_days = getattr(self, 'lookback_days', 60)

        # Calculate raw signal for each instrument
        for instrument in instruments:
            try:
                # Get price history from market data
                lookback_date = as_of - timedelta(days=lookback_days + 10)  # Extra buffer
                price_history = market_data.get_price_history(
                    instrument,
                    start_date=lookback_date,
                    end_date=as_of
                )

                # Calculate raw signal (subclass implements this)
                raw_signal = self._calculate_raw_signal(
                    inst_data=price_history,
                    market_data=market_data,
                    as_of=as_of
                )

                raw_signals[instrument] = raw_signal

            except Exception as e:
                # Handle errors gracefully
                print(f"Warning: Error calculating {self.name} for {instrument}: {e}")
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
