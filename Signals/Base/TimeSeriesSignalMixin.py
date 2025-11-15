# ABOUTME: Mixin providing common time-series signal functionality (calculate, standardize, history tracking)
# ABOUTME: Used by MomentumSignal, MeanReversionSignal, and other time-series signals to eliminate duplication

from datetime import date, timedelta
from typing import Dict, List, Any, Optional
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
