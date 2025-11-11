# ABOUTME: AlphaGenerator converts signals (Z-scores) to expected returns (alphas)
# ABOUTME: Implements IC × Vol × Z formula from Grinold-Kahn framework
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
from typing import Dict
import pandas as pd

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
        vol_estimator: VolatilityEstimator = None
    ):
        """
        Initialize alpha generator.

        Args:
            IC: Information Coefficient (default: 0.05)
                Measures forecasting skill (correlation between forecast and realized)
                Typical range: 0.02 - 0.10
            vol_estimator: Volatility estimator (default: RealizedVolatility())

        Example:
            Conservative (low IC):
            >>> alpha_gen = AlphaGenerator(IC=0.03)

            Aggressive (high IC, confident in signals):
            >>> alpha_gen = AlphaGenerator(IC=0.10)

            Custom vol estimator:
            >>> from Risk.Volatility.EWMAVolatility import EWMAVolatility
            >>> alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=EWMAVolatility(halflife=20))
        """
        self.IC = IC
        self.vol_estimator = vol_estimator or RealizedVolatility()

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
                alpha = self.IC * vol * z_score
                alphas[asset] = alpha

        return alphas
