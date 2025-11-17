# ABOUTME: Trading signal based on PCA factor analysis of yield curves
# ABOUTME: Generates signals from level/slope/curvature factor extremes and mean reversion

"""
PCA Factor-Based Trading Signals

Generates trading signals based on PCA factor analysis of yield curve movements.
Signals can be based on:
- Factor extremes (z-score)
- Factor mean reversion
- Factor momentum
- Factor spreads

Common strategies:
- Fade extreme slope (slope z-score > 2 or < -2)
- Curve flattener when slope is steep
- Butterfly when curvature is extreme

Usage:
    >>> from Signals.PCAFactorSignal import PCAFactorSignal
    >>> signal = PCAFactorSignal(
    ...     lookback_days=252,
    ...     target_factor="slope",
    ...     strategy="mean_reversion",
    ...     z_threshold=2.0
    ... )
    >>> score = signal.evaluate(as_of_date, historical_curves)
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Literal

import numpy as np
import polars as pl

from Risk.FactorDecomposition import PCAFactorModel


@dataclass
class PCAFactorSignal:
    """
    Trading signal based on PCA factor analysis.

    Generates signals by analyzing factor extremes, mean reversion,
    or momentum in yield curve factors.

    Attributes:
        lookback_days: Historical window for PCA fit
        target_factor: Which factor to trade ("level", "slope", "curvature", or "all")
        strategy: Signal strategy ("mean_reversion", "momentum", "extreme_fade")
        refit_frequency: Days between PCA refits (default: 20)
        z_threshold: Z-score threshold for extreme signals (default: 2.0)
        momentum_window: Window for momentum calculation (default: 20)
    """

    lookback_days: int = 252
    target_factor: Literal["level", "slope", "curvature", "all"] = "slope"
    strategy: Literal["mean_reversion", "momentum", "extreme_fade"] = "mean_reversion"
    refit_frequency: int = 20
    z_threshold: float = 2.0
    momentum_window: int = 20

    # Internal state
    _pca_model: Optional[PCAFactorModel] = field(default=None, init=False, repr=False)
    _last_fit_date: Optional[date] = field(default=None, init=False, repr=False)
    _factor_history: Optional[pl.DataFrame] = field(default=None, init=False, repr=False)

    def evaluate(
        self,
        as_of_date: date,
        curve_history: pl.DataFrame,
        tenor_columns: Optional[List[str]] = None
    ) -> float:
        """
        Evaluate signal on a given date.

        Args:
            as_of_date: Date to generate signal for
            curve_history: DataFrame with date column and tenor level columns
            tenor_columns: List of tenor column names (if None, auto-detect)

        Returns:
            Signal score (typically -1 to +1, where positive = bullish/steepen)

        Example:
            >>> curve_history = pl.DataFrame({
            ...     "date": dates,
            ...     "1Y": yield_1y,
            ...     "2Y": yield_2y,
            ...     "5Y": yield_5y,
            ...     "10Y": yield_10y
            ... })
            >>> score = signal.evaluate(date(2024, 6, 1), curve_history)
        """
        # Validate inputs
        if "date" not in curve_history.columns:
            raise ValueError("curve_history must have 'date' column")

        # Auto-detect tenor columns if not provided
        if tenor_columns is None:
            tenor_columns = [col for col in curve_history.columns if col != "date"]

        # Filter to lookback window
        start_date = as_of_date - timedelta(days=self.lookback_days)
        lookback_data = curve_history.filter(
            (pl.col("date") >= start_date) & (pl.col("date") <= as_of_date)
        )

        if lookback_data.height < 30:
            raise ValueError(f"Insufficient historical data: {lookback_data.height} days")

        # Compute yield curve changes
        changes = self._compute_changes(lookback_data, tenor_columns)

        # Refit PCA if needed
        days_since_fit = None
        if self._last_fit_date is not None:
            days_since_fit = (as_of_date - self._last_fit_date).days

        if self._pca_model is None or days_since_fit is None or days_since_fit >= self.refit_frequency:
            self._pca_model = PCAFactorModel(n_components=3)
            self._pca_model.fit(changes, date_column="date")
            self._last_fit_date = as_of_date

            # Extract factor history
            self._update_factor_history(changes)

        # Get current factors
        current_factors = self._pca_model.get_factors(as_of_date)

        # Generate signal based on strategy
        if self.strategy == "mean_reversion":
            return self._mean_reversion_signal(current_factors)
        elif self.strategy == "momentum":
            return self._momentum_signal(as_of_date)
        elif self.strategy == "extreme_fade":
            return self._extreme_fade_signal(current_factors)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")

    def _compute_changes(self, curve_data: pl.DataFrame, tenor_columns: List[str]) -> pl.DataFrame:
        """Compute first differences of yield curves."""
        # Sort by date
        curve_data = curve_data.sort("date")

        # Compute changes for each tenor
        changes_dict = {"date": curve_data["date"].to_list()[1:]}  # Drop first date

        for tenor in tenor_columns:
            levels = curve_data[tenor].to_numpy()
            changes = np.diff(levels)
            changes_dict[tenor] = changes.tolist()

        return pl.DataFrame(changes_dict)

    def _update_factor_history(self, changes: pl.DataFrame):
        """Update internal factor history DataFrame."""
        factor_data = {
            "date": self._pca_model.dates,
            "level": self._pca_model.factor_scores[:, 0],
            "slope": self._pca_model.factor_scores[:, 1],
            "curvature": self._pca_model.factor_scores[:, 2],
        }
        self._factor_history = pl.DataFrame(factor_data)

    def _mean_reversion_signal(self, current_factors: Dict[str, float]) -> float:
        """
        Mean reversion signal: fade extremes in target factor.

        Logic:
        - If factor z-score > threshold: signal to fade (expect reversion)
        - If factor z-score < -threshold: signal to fade (expect reversion)
        - Magnitude = z-score capped at ±3

        Returns:
            Signal in range [-1, +1] (negative = bearish/flatten, positive = bullish/steepen)
        """
        if self._factor_history is None:
            return 0.0

        # Get target factor history
        if self.target_factor == "all":
            # Combine all factors (weighted average)
            factor_value = (
                current_factors["level"] * 0.5 +
                current_factors["slope"] * 0.3 +
                current_factors["curvature"] * 0.2
            )
            history = (
                self._factor_history["level"] * 0.5 +
                self._factor_history["slope"] * 0.3 +
                self._factor_history["curvature"] * 0.2
            )
        else:
            factor_value = current_factors[self.target_factor]
            history = self._factor_history[self.target_factor]

        # Calculate z-score
        mean = history.mean()
        std = history.std()

        if std < 1e-10:
            return 0.0

        z_score = (factor_value - mean) / std

        # Mean reversion signal: fade extremes
        # Positive z-score (extreme high) → negative signal (fade/sell)
        # Negative z-score (extreme low) → positive signal (fade/buy)
        signal = -np.sign(z_score) * min(abs(z_score) / 3.0, 1.0)

        return float(signal)

    def _momentum_signal(self, as_of_date: date) -> float:
        """
        Momentum signal: follow factor trends.

        Logic:
        - Calculate factor change over momentum window
        - Positive change → positive signal (trend continuation)
        - Normalized by historical volatility

        Returns:
            Signal in range [-1, +1]
        """
        if self._factor_history is None:
            return 0.0

        # Filter to momentum window
        start_date = as_of_date - timedelta(days=self.momentum_window)
        recent = self._factor_history.filter(
            (pl.col("date") >= start_date) & (pl.col("date") <= as_of_date)
        )

        if recent.height < 2:
            return 0.0

        # Get target factor series
        if self.target_factor == "all":
            factor_series = (
                recent["level"] * 0.5 +
                recent["slope"] * 0.3 +
                recent["curvature"] * 0.2
            )
        else:
            factor_series = recent[self.target_factor]

        # Calculate momentum (change from start to end)
        momentum = factor_series.to_list()[-1] - factor_series.to_list()[0]

        # Normalize by historical volatility
        if self.target_factor == "all":
            history = (
                self._factor_history["level"] * 0.5 +
                self._factor_history["slope"] * 0.3 +
                self._factor_history["curvature"] * 0.2
            )
        else:
            history = self._factor_history[self.target_factor]

        std = history.std()

        if std < 1e-10:
            return 0.0

        # Normalize and cap at ±1
        normalized_momentum = momentum / (std * np.sqrt(self.momentum_window / 252))
        signal = np.clip(normalized_momentum, -1.0, 1.0)

        return float(signal)

    def _extreme_fade_signal(self, current_factors: Dict[str, float]) -> float:
        """
        Extreme fade signal: only trade when factor is extreme.

        Logic:
        - Calculate z-score
        - If abs(z-score) > threshold: fade the extreme
        - Otherwise: no signal

        Returns:
            Signal in range [-1, +1], often 0 when not extreme
        """
        if self._factor_history is None:
            return 0.0

        # Get target factor
        if self.target_factor == "all":
            factor_value = (
                current_factors["level"] * 0.5 +
                current_factors["slope"] * 0.3 +
                current_factors["curvature"] * 0.2
            )
            history = (
                self._factor_history["level"] * 0.5 +
                self._factor_history["slope"] * 0.3 +
                self._factor_history["curvature"] * 0.2
            )
        else:
            factor_value = current_factors[self.target_factor]
            history = self._factor_history[self.target_factor]

        # Calculate z-score
        mean = history.mean()
        std = history.std()

        if std < 1e-10:
            return 0.0

        z_score = (factor_value - mean) / std

        # Only signal when extreme
        if abs(z_score) < self.z_threshold:
            return 0.0

        # Fade the extreme (stronger signal for more extreme values)
        signal = -np.sign(z_score) * min((abs(z_score) - self.z_threshold) / 2.0, 1.0)

        return float(signal)

    def get_current_factor_values(self) -> Optional[Dict[str, float]]:
        """Get most recent factor values if model is fitted."""
        if self._pca_model is None or self._pca_model.dates is None:
            return None

        latest_date = max(self._pca_model.dates)
        return self._pca_model.get_factors(latest_date)

    def get_factor_statistics(self) -> Optional[Dict[str, Dict[str, float]]]:
        """Get statistical summary of factor history."""
        if self._factor_history is None:
            return None

        stats = {}
        for factor in ["level", "slope", "curvature"]:
            series = self._factor_history[factor]
            stats[factor] = {
                "mean": float(series.mean()),
                "std": float(series.std()),
                "min": float(series.min()),
                "max": float(series.max()),
                "current": float(series.to_list()[-1]),
                "z_score": float((series.to_list()[-1] - series.mean()) / series.std())
                if series.std() > 1e-10
                else 0.0,
            }

        return stats
