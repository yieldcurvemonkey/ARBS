# ABOUTME: AlphaGenerator converts signals (Z-scores) to expected returns (alphas)
# ABOUTME: Supports static and dynamic (time-varying) IC estimation from historical performance
"""
AlphaGenerator - Signal to Expected Return Conversion

Converts signal Z-scores to expected returns (alphas) using:

    α_i = IC × σ_i × z_i

Where:
- α_i = expected return for asset i (alpha)
- IC = Information Coefficient (forecast skill)
- σ_i = volatility of asset i
- z_i = signal Z-score for asset i

Critical Insight:
    Signals are dimensionless Z-scores (e.g., Z=2.0)
    Alphas are expected RETURNS (e.g., α=0.01 = 1%)

    Without this conversion:
        Z=2.0 → optimizer treats as 200% expected return (absurd!)

    With conversion (IC=0.05, Vol=10%):
        Z=2.0 → α = 0.05 × 0.10 × 2.0 = 0.01 = 1% (sensible!)

Grinold-Kahn Framework:
    Information Ratio: IR = IC × √BR
    where:
        IC = Corr(α, r) (correlation between forecast and realized returns)
        BR = Breadth (number of independent bets)

    IC measures forecasting skill:
        IC = 0.00 → no skill (random)
        IC = 0.05 → typical for quant strategies
        IC = 0.10 → very good
        IC = 1.00 → perfect foresight (impossible)

Example:
    >>> alpha_gen = AlphaGenerator(IC=0.05)
    >>> signals = {'SFRZ4': 1.5}  # Strong carry signal
    >>> returns_history = pd.DataFrame({'SFRZ4': [0.01, -0.01, ...]})
    >>> alphas = alpha_gen.signals_to_alphas(signals, returns_history, as_of)
    >>> alphas['SFRZ4']
    0.0075  # 0.75% expected return (sensible, not 150%!)
"""

from datetime import date
from typing import Dict, Optional
import pandas as pd
import numpy as np

from Risk.Volatility.VolatilityEstimator import VolatilityEstimator
from Risk.Volatility.RealizedVolatility import RealizedVolatility


class AlphaGenerator:
    """
    Convert signal Z-scores to expected returns (alphas).

    Applies Grinold-Kahn formula: α = IC × Vol × Z

    Attributes:
        IC: Information Coefficient (forecast skill)
        vol_estimator: Volatility estimator for assets

    Methods:
        signals_to_alphas: Convert signals → alphas

    Example:
        >>> alpha_gen = AlphaGenerator(IC=0.05)
        >>> signals = {'SFRZ4': 2.0, 'SFRH5': -1.0}
        >>> returns_history = pd.DataFrame({
        ...     'SFRZ4': [0.01, -0.01, 0.02, ...],
        ...     'SFRH5': [0.005, -0.005, 0.01, ...]
        ... })
        >>> alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))
        >>> alphas
        {'SFRZ4': 0.010, 'SFRH5': -0.0075}  # Expected returns, not Z-scores!
    """

    def __init__(
        self,
        IC: float = 0.05,
        vol_estimator: VolatilityEstimator = None,
        dynamic_ic: bool = False,
        ic_method: str = "rolling",
        ic_lookback: int = 60,
        ic_halflife: int = 30,
        ic_min_periods: int = 20
    ):
        """
        Initialize alpha generator.

        Args:
            IC: Information Coefficient (default: 0.05)
                Measures forecasting skill (correlation between forecast and realized)
                Typical range: 0.02 - 0.10
                Used as fallback if dynamic_ic is False or insufficient history
            vol_estimator: Volatility estimator (default: RealizedVolatility())
            dynamic_ic: Enable dynamic (time-varying) IC estimation (default: False)
            ic_method: Method for dynamic IC estimation (default: "rolling")
                Options: "rolling", "ewma", "regime"
            ic_lookback: Lookback window for rolling IC calculation (default: 60)
            ic_halflife: Half-life for EWMA IC calculation (default: 30)
            ic_min_periods: Minimum periods required for dynamic IC (default: 20)

        Example:
            Static IC (original behavior):
            >>> alpha_gen = AlphaGenerator(IC=0.05)

            Dynamic IC with rolling window:
            >>> alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="rolling", ic_lookback=60)

            Dynamic IC with exponential weighting:
            >>> alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="ewma", ic_halflife=30)

            Regime-aware IC:
            >>> alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="regime")
        """
        self.IC = IC
        self.vol_estimator = vol_estimator or RealizedVolatility()
        self.dynamic_ic = dynamic_ic
        self.ic_method = ic_method
        self.ic_lookback = ic_lookback
        self.ic_halflife = ic_halflife
        self.ic_min_periods = ic_min_periods

        # Store IC history for EWMA method
        self._ic_history = []

    def signals_to_alphas(
        self,
        signals: Dict[str, float],
        returns_history: pd.DataFrame,
        as_of: date
    ) -> Dict[str, float]:
        """
        Convert signal Z-scores to expected returns (alphas).

        Formula:
            α_i = IC × σ_i × z_i

        Where:
            α_i = expected return for asset i
            IC = Information Coefficient (forecast skill)
            σ_i = volatility of asset i (from returns_history)
            z_i = signal Z-score for asset i

        Args:
            signals: Map from asset → Z-score
                    Z-scores are standardized signals (mean=0, std=1)
            returns_history: Historical returns for volatility estimation
                             DataFrame with columns = assets, rows = time
            as_of: Current date (for potential time-varying IC)

        Returns:
            Map from asset → expected return (alpha)

        Example:
            >>> signals = {'SFRZ4': 1.5}  # Strong signal (1.5 std devs)
            >>> returns_history = pd.DataFrame({'SFRZ4': [...]})  # 10% vol
            >>> alphas = alpha_gen.signals_to_alphas(signals, returns_history, as_of)
            >>> alphas['SFRZ4']
            0.0075  # IC(0.05) × Vol(0.10) × Z(1.5) = 0.75% expected return

        Note:
            This is the critical missing piece in the current implementation!
            Without this, Z-scores are treated as expected returns directly,
            leading to absurd predictions (Z=2.0 → 200% return).
        """
        # Estimate volatilities from returns history
        volatilities = self.vol_estimator.estimate(returns_history)

        # Determine IC to use (static or dynamic)
        ic_to_use = self.IC  # Default to static IC

        # Convert signals → alphas using IC × Vol × Z
        alphas = {}
        for asset, z_score in signals.items():
            # Get volatility for this asset
            vol = volatilities.get(asset, 0.0)

            # If no volatility estimate (missing history), default to 0 alpha
            if vol == 0.0:
                alphas[asset] = 0.0
            else:
                # Apply Grinold-Kahn formula
                alpha = ic_to_use * vol * z_score
                alphas[asset] = alpha

        return alphas

    def estimate_dynamic_ic(
        self,
        signals_history: pd.DataFrame,
        returns_history: pd.DataFrame,
        as_of: Optional[date] = None
    ) -> float:
        """
        Estimate Information Coefficient (IC) dynamically from historical performance.

        IC measures the correlation between forecasts (signals) and realized returns.
        Dynamic IC adapts to changing market conditions and signal decay.

        Methods:
            1. Rolling IC: Simple rolling window correlation
            2. Exponentially Weighted IC: Recent performance weighted more heavily
            3. Regime-Aware IC: Different IC for different market regimes

        Args:
            signals_history: Historical signals (DataFrame with columns = assets, index = dates)
                            Values should be Z-scores from signal generation
            returns_history: Realized returns (DataFrame with columns = assets, index = dates)
                             Returns should be forward-looking (returns AFTER signal)
            as_of: Current date (for regime detection). If None, uses last date in history

        Returns:
            Estimated IC (float between -1 and 1, typically 0.02 - 0.10)

        Example:
            >>> # Rolling IC
            >>> alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="rolling", ic_lookback=60)
            >>> signals = pd.DataFrame({'SFRZ4': [1.5, 2.0, ...], ...})
            >>> returns = pd.DataFrame({'SFRZ4': [0.01, -0.01, ...], ...})
            >>> ic = alpha_gen.estimate_dynamic_ic(signals, returns)
            >>> ic
            0.073  # Current IC is higher than static 0.05

        Note:
            Signals and returns must be properly aligned:
            - signals.loc[t] should predict returns.loc[t+1]
            - Use shift() to ensure signals don't look ahead
        """
        # Validate inputs
        if signals_history.empty or returns_history.empty:
            return self.IC  # Fallback to static IC

        # Align signals and returns (ensure same assets and dates)
        common_assets = list(set(signals_history.columns) & set(returns_history.columns))
        if not common_assets:
            return self.IC  # No common assets, fallback to static IC

        # Filter to common assets and dates
        signals = signals_history[common_assets].copy()
        returns = returns_history[common_assets].copy()

        # Align by index (dates)
        common_dates = signals.index.intersection(returns.index)
        if len(common_dates) < self.ic_min_periods:
            return self.IC  # Insufficient history, fallback to static IC

        signals = signals.loc[common_dates]
        returns = returns.loc[common_dates]

        # Estimate IC based on method
        if self.ic_method == "rolling":
            ic = self._estimate_rolling_ic(signals, returns)
        elif self.ic_method == "ewma":
            ic = self._estimate_ewma_ic(signals, returns)
        elif self.ic_method == "regime":
            ic = self._estimate_regime_ic(signals, returns, as_of)
        else:
            raise ValueError(f"Unknown ic_method: {self.ic_method}. Options: 'rolling', 'ewma', 'regime'")

        # Sanity check: IC should be valid
        # IC is a correlation coefficient, so it must be between -1 and 1
        if np.isnan(ic) or np.isinf(ic):
            return self.IC

        # Clip IC to valid range [-1, 1] just in case
        ic = np.clip(ic, -1.0, 1.0)

        return ic

    def _estimate_rolling_ic(
        self,
        signals: pd.DataFrame,
        returns: pd.DataFrame
    ) -> float:
        """
        Estimate IC using rolling window correlation.

        IC_t = Corr(signals_{t-N:t-1}, returns_{t-N+1:t})

        Simple, interpretable, but can be noisy with small windows.
        """
        # Use last ic_lookback periods
        lookback = min(self.ic_lookback, len(signals))
        signals_window = signals.iloc[-lookback:]
        returns_window = returns.iloc[-lookback:]

        # Flatten signals and returns for correlation calculation
        signals_flat = signals_window.values.flatten()
        returns_flat = returns_window.values.flatten()

        # Remove NaN pairs
        valid_mask = ~(np.isnan(signals_flat) | np.isnan(returns_flat))
        signals_valid = signals_flat[valid_mask]
        returns_valid = returns_flat[valid_mask]

        if len(signals_valid) < self.ic_min_periods:
            return self.IC  # Insufficient valid observations

        # Calculate correlation (IC)
        ic = np.corrcoef(signals_valid, returns_valid)[0, 1]

        return ic

    def _estimate_ewma_ic(
        self,
        signals: pd.DataFrame,
        returns: pd.DataFrame
    ) -> float:
        """
        Estimate IC using Exponentially Weighted Moving Average.

        IC_t = EWMA(IC_{t-1}, IC_observed, halflife)

        Recent observations weighted more heavily. Better adapts to regime changes.
        """
        # Calculate IC for each period
        period_ics = []

        for i in range(len(signals)):
            # Get signals and returns for this period
            signals_period = signals.iloc[i].values
            returns_period = returns.iloc[i].values

            # Remove NaN pairs
            valid_mask = ~(np.isnan(signals_period) | np.isnan(returns_period))
            signals_valid = signals_period[valid_mask]
            returns_valid = returns_period[valid_mask]

            # Need at least 2 observations to calculate correlation
            if len(signals_valid) < 2:
                continue

            # Calculate correlation for this period (cross-sectional IC)
            period_ic = np.corrcoef(signals_valid, returns_valid)[0, 1]

            if not np.isnan(period_ic):
                period_ics.append(period_ic)

        if len(period_ics) < self.ic_min_periods:
            return self.IC  # Insufficient observations

        # Apply EWMA
        ic_series = pd.Series(period_ics)
        ewma_ic = ic_series.ewm(halflife=self.ic_halflife, min_periods=self.ic_min_periods).mean().iloc[-1]

        return ewma_ic

    def _estimate_regime_ic(
        self,
        signals: pd.DataFrame,
        returns: pd.DataFrame,
        as_of: Optional[date]
    ) -> float:
        """
        Estimate IC based on current market regime.

        Regimes:
            - High volatility vs Low volatility
            - Trending vs Ranging markets

        Different signals perform differently in different regimes.
        """
        # Calculate current regime based on recent volatility
        # High vol = recent realized vol > historical average
        # Low vol = recent realized vol < historical average

        # Calculate rolling volatility
        returns_std = returns.std(axis=1)  # Cross-sectional std per date

        if len(returns_std) < self.ic_min_periods:
            return self.IC  # Insufficient history

        # Recent volatility (last 20 periods)
        recent_vol = returns_std.iloc[-20:].mean()

        # Historical average volatility
        hist_vol = returns_std.mean()

        # Determine regime
        is_high_vol = recent_vol > hist_vol

        # Split history into high vol and low vol periods
        high_vol_mask = returns_std > hist_vol
        low_vol_mask = returns_std <= hist_vol

        # Calculate IC for current regime
        if is_high_vol:
            # Use high vol periods
            signals_regime = signals[high_vol_mask]
            returns_regime = returns[high_vol_mask]
        else:
            # Use low vol periods
            signals_regime = signals[low_vol_mask]
            returns_regime = returns[low_vol_mask]

        # Calculate IC for this regime using rolling method
        if len(signals_regime) < self.ic_min_periods:
            return self.IC  # Insufficient regime observations

        # Flatten and calculate correlation
        signals_flat = signals_regime.values.flatten()
        returns_flat = returns_regime.values.flatten()

        valid_mask = ~(np.isnan(signals_flat) | np.isnan(returns_flat))
        signals_valid = signals_flat[valid_mask]
        returns_valid = returns_flat[valid_mask]

        if len(signals_valid) < self.ic_min_periods:
            return self.IC

        ic = np.corrcoef(signals_valid, returns_valid)[0, 1]

        return ic

    def signals_to_alphas_with_dynamic_ic(
        self,
        signals: Dict[str, float],
        returns_history: pd.DataFrame,
        signals_history: pd.DataFrame,
        as_of: date
    ) -> Dict[str, float]:
        """
        Convert signals to alphas using dynamic IC estimation.

        This is a convenience method that combines estimate_dynamic_ic() and signals_to_alphas().

        Args:
            signals: Current signals (map from asset → Z-score)
            returns_history: Historical returns for IC estimation and volatility
            signals_history: Historical signals for IC estimation
            as_of: Current date

        Returns:
            Map from asset → expected return (alpha)

        Example:
            >>> alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="ewma")
            >>> signals = {'SFRZ4': 2.0}
            >>> returns_hist = pd.DataFrame({...})  # Historical returns
            >>> signals_hist = pd.DataFrame({...})  # Historical signals
            >>> alphas = alpha_gen.signals_to_alphas_with_dynamic_ic(
            ...     signals, returns_hist, signals_hist, date(2024, 11, 1)
            ... )
        """
        if self.dynamic_ic:
            # Estimate IC from historical performance
            estimated_ic = self.estimate_dynamic_ic(signals_history, returns_history, as_of)

            # Temporarily override IC
            original_ic = self.IC
            self.IC = estimated_ic

            # Generate alphas with dynamic IC
            alphas = self.signals_to_alphas(signals, returns_history, as_of)

            # Restore original IC
            self.IC = original_ic

            return alphas
        else:
            # Use static IC
            return self.signals_to_alphas(signals, returns_history, as_of)
