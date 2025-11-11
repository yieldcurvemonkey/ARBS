# ABOUTME: Abstract base class for all alpha signals in the Grinold-Kahn framework
# ABOUTME: Provides standardized signal generation, z-score normalization, and IC calculation
"""
BaseSignal - Abstract base class for all alpha signals

Implements the Grinold-Kahn signal framework with:
- Standardized alpha generation (z-scores)
- Information Coefficient (IC) tracking
- Signal metadata and history
- Batch generation for multiple instruments

Design principles from 2025 research (AlphaEval framework):
1. Predictive power: IC, Rank IC
2. Stability: IC time-series consistency
3. Robustness: Performance under perturbations
4. Financial logic: Interpretability
5. Diversity: Low correlation with other signals
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, List, Optional
import numpy as np
import pandas as pd


class BaseSignal(ABC):
    """
    Abstract base class for alpha signals.

    All signals must implement _calculate_raw_signal() which returns
    the raw signal value before standardization.

    Attributes:
        name (str): Signal name for identification
        standardize (bool): Whether to z-score alphas (default: True)
        last_generated (date): Date of last signal generation
        history (dict): Historical signal values and metadata
    """

    def __init__(
        self,
        name: str,
        standardize: bool = True,
        track_history: bool = True,
    ):
        """
        Initialize base signal.

        Args:
            name: Signal name (e.g., "futures_carry", "momentum")
            standardize: If True, return z-scored alphas (mean=0, std=1)
            track_history: If True, store signal generation history
        """
        self.name = name
        self.standardize = standardize
        self.track_history = track_history
        self.last_generated: Optional[date] = None
        self.history: dict = {} if track_history else None

    @abstractmethod
    def _calculate_raw_signal(
        self,
        inst_data: pd.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Calculate raw signal value for a single instrument.

        This method must be implemented by subclasses.

        Args:
            inst_data: Instrument-specific data (prices, rates, etc.)
            market_data: Market-wide data (curves, vol surface, etc.)
            as_of: Calculation date

        Returns:
            Raw signal value (before standardization)
        """
        pass

    def generate(
        self,
        inst_data: pd.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """
        Generate alpha signal for a single instrument.

        Args:
            inst_data: Instrument-specific data
            market_data: Market-wide data
            as_of: Calculation date

        Returns:
            Alpha value (standardized if standardize=True)
        """
        # Calculate raw signal
        raw_signal = self._calculate_raw_signal(inst_data, market_data, as_of)

        # Update metadata
        self.last_generated = as_of

        # Track history if enabled
        if self.track_history:
            if as_of not in self.history:
                self.history[as_of] = []
            self.history[as_of].append(raw_signal)

        # Return raw or standardized
        # Note: Single value can't be standardized (need cross-section)
        return raw_signal

    def generate_batch(
        self,
        inst_data_list: List[pd.DataFrame],
        market_data: Optional[Any],
        as_of: date,
    ) -> np.ndarray:
        """
        Generate alpha signals for multiple instruments.

        This is the primary method for portfolio construction, as it
        generates cross-sectional signals that can be standardized.

        Args:
            inst_data_list: List of instrument-specific data
            market_data: Market-wide data (shared across instruments)
            as_of: Calculation date

        Returns:
            Array of alpha values (standardized if standardize=True)
        """
        # Calculate raw signals for all instruments
        raw_signals = np.array([
            self._calculate_raw_signal(inst_data, market_data, as_of)
            for inst_data in inst_data_list
        ])

        # Update metadata
        self.last_generated = as_of

        # Track history if enabled
        if self.track_history:
            self.history[as_of] = raw_signals.copy()

        # Standardize if requested
        if self.standardize:
            return self._standardize(raw_signals)
        else:
            return raw_signals

    def _standardize(self, signals: np.ndarray) -> np.ndarray:
        """
        Standardize signals to z-scores (mean=0, std=1).

        This is the standard approach in Grinold-Kahn framework,
        making signals comparable across different signal types.

        Args:
            signals: Raw signal values

        Returns:
            Z-scored signals
        """
        # Handle edge cases
        if len(signals) < 2:
            # Can't standardize single value
            return signals

        # Remove NaN values for calculation
        valid_mask = ~np.isnan(signals)
        if not np.any(valid_mask):
            return signals  # All NaN

        # Calculate z-scores
        mean = np.mean(signals[valid_mask])
        std = np.std(signals[valid_mask], ddof=1)

        if std < 1e-10:
            # Zero variance → all signals equal → return zeros
            return np.zeros_like(signals)

        # Standardize: z = (x - mean) / std
        z_scores = (signals - mean) / std

        return z_scores

    def get_history(self, start_date: Optional[date] = None) -> pd.DataFrame:
        """
        Get signal generation history.

        Args:
            start_date: If provided, filter history from this date

        Returns:
            DataFrame with columns: date, signal_values
        """
        if not self.track_history:
            raise ValueError("Signal history tracking is disabled")

        if not self.history:
            return pd.DataFrame(columns=["date", "signal_values"])

        # Convert history dict to DataFrame
        data = []
        for as_of, values in self.history.items():
            if start_date is None or as_of >= start_date:
                data.append({
                    "date": as_of,
                    "signal_values": values if isinstance(values, (list, np.ndarray)) else [values],
                })

        return pd.DataFrame(data)

    def calculate_ic(
        self,
        forecasts: pd.Series,
        actuals: pd.Series,
    ) -> float:
        """
        Calculate Information Coefficient for this signal.

        IC measures the correlation between signal forecasts and actual returns.
        Target: IC > 0.05 (good), IC > 0.10 (very good), IC > 0.15 (exceptional)

        Args:
            forecasts: Signal values (alphas)
            actuals: Actual returns

        Returns:
            IC (Pearson correlation)
        """
        from Signals.Utils.IC import calculate_ic
        return calculate_ic(forecasts.values, actuals.values)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', standardize={self.standardize})"
