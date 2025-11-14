# ABOUTME: GrinoldKahnPortfolio integrates signals, alpha generation, risk models, and optimization
# ABOUTME: Implements complete Grinold-Kahn framework as an Asset for composition
"""
GrinoldKahnPortfolio - Integrated Grinold-Kahn Strategy

Implements the complete Grinold-Kahn framework as a Portfolio Asset:
1. Signal generation (Z-scores)
2. Alpha conversion (IC × Vol × Z)
3. Risk estimation (covariance matrix)
4. Portfolio optimization (mean-variance)

This IS-A Asset, enabling:
- Composition with other portfolios
- Backtesting like any other asset
- Nested portfolio structures

Grinold-Kahn Workflow:
    Signals → Z-scores → Alphas → Optimization → Weights → Returns

Formula:
    α_i = IC × σ_i × z_i
    weights = argmax(α'w - λ/2 × w'Σw)
    r_portfolio = Σ(w_i × r_i)

Example:
    >>> carry_signal = CarrySignal()
    >>> gk_portfolio = GrinoldKahnPortfolio(
    ...     identifier='GK_CARRY',
    ...     signals=[carry_signal],
    ...     alpha_generator=AlphaGenerator(IC=0.05),
    ...     risk_model=LedoitWolfShrinkage(),
    ...     optimizer=MeanVarianceOptimizer(risk_aversion=1.0)
    ... )
    >>>
    >>> # Generate optimal weights
    >>> weights = gk_portfolio.generate_weights(
    ...     instruments=['SFRZ4', 'SFRH5', 'SFRM5'],
    ...     returns_history=returns_df,
    ...     market_data=mdp,
    ...     as_of=date(2024, 11, 1)
    ... )
    >>>
    >>> # Calculate portfolio return
    >>> realized_returns = {'SFRZ4': 0.015, 'SFRH5': 0.010, 'SFRM5': 0.012}
    >>> port_return = gk_portfolio.calculate_return(realized_returns, weights)
"""

from datetime import date
from typing import Dict, List, Optional, Any
import polars as pl
import numpy as np

from Asset.Base import Asset, AssetTransition
from Signals.Base.BaseSignal import BaseSignal
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Risk.Volatility.RealizedVolatility import RealizedVolatility
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer


class GrinoldKahnPortfolio(Asset):
    """
    Portfolio implementing Grinold-Kahn framework.

    Combines signals, alpha generation, risk modeling, and optimization
    into a cohesive strategy following the Fundamental Law of Active Management:

        IR = IC × √BR

    Where:
        IR = Information Ratio (risk-adjusted excess return)
        IC = Information Coefficient (forecast skill)
        BR = Breadth (number of independent bets)

    Attributes:
        identifier: Portfolio name
        signals: List of BaseSignal objects generating Z-scores
        alpha_generator: Converts Z-scores → expected returns
        risk_model: Estimates covariance matrix
        optimizer: Generates optimal weights
        rebalance_frequency: How often to rebalance ('daily', 'weekly', 'monthly')

    Methods:
        generate_weights: Signal → Alpha → Optimization → Weights
        calculate_return: Weights + Returns → Portfolio Return

    Example:
        >>> gk_port = GrinoldKahnPortfolio(
        ...     identifier='GK_MULTI',
        ...     signals=[CarrySignal(), MomentumSignal()],
        ...     alpha_generator=AlphaGenerator(IC=0.05),
        ...     risk_model=LedoitWolfShrinkage(),
        ...     optimizer=MeanVarianceOptimizer(risk_aversion=1.0)
        ... )
    """

    def __init__(
        self,
        identifier: str,
        signals: List[BaseSignal],
        alpha_generator: Optional[AlphaGenerator] = None,
        risk_model: Optional[Any] = None,
        optimizer: Optional[MeanVarianceOptimizer] = None,
        rebalance_frequency: str = "weekly"
    ):
        """
        Initialize GrinoldKahnPortfolio.

        Args:
            identifier: Portfolio name (e.g., 'GK_CARRY', 'GK_MULTI_SIGNAL')
            signals: List of signals generating Z-scores
            alpha_generator: Converts signals → alphas (default: IC=0.05)
            risk_model: Covariance estimator (default: LedoitWolfShrinkage)
            optimizer: Portfolio optimizer (default: MeanVarianceOptimizer)
            rebalance_frequency: Rebalancing schedule (default: 'weekly')

        Example:
            Basic construction:
            >>> portfolio = GrinoldKahnPortfolio(
            ...     identifier='GK_CARRY',
            ...     signals=[CarrySignal()]
            ... )

            Full customization:
            >>> portfolio = GrinoldKahnPortfolio(
            ...     identifier='GK_CUSTOM',
            ...     signals=[CarrySignal(), MomentumSignal()],
            ...     alpha_generator=AlphaGenerator(IC=0.10),
            ...     risk_model=SampleCovariance(),
            ...     optimizer=MeanVarianceOptimizer(risk_aversion=2.0),
            ...     rebalance_frequency='monthly'
            ... )
        """
        self.identifier = identifier
        self.signals = signals
        self.alpha_generator = alpha_generator or AlphaGenerator(IC=0.05)
        self.risk_model = risk_model or LedoitWolfShrinkage()
        self.optimizer = optimizer or MeanVarianceOptimizer(risk_aversion=1.0)
        self.rebalance_frequency = rebalance_frequency

        # Track state
        self.current_weights: Optional[Dict[str, float]] = None
        self.last_rebalance: Optional[date] = None

    def get_identifier(self) -> str:
        """
        Return portfolio identifier.

        Returns:
            Portfolio name string

        Example:
            >>> portfolio = GrinoldKahnPortfolio(identifier='GK_CARRY', signals=[...])
            >>> portfolio.get_identifier()
            'GK_CARRY'
        """
        return self.identifier

    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        Detect asset transition (roll, expiry, etc.).

        For GrinoldKahnPortfolio, transitions are not applicable at the portfolio level.
        Individual constituents may have transitions, but those are handled separately.

        Args:
            as_of: Current date
            market_data: Market data (unused for portfolio)

        Returns:
            None (portfolios don't have transitions)

        Note:
            If needed, transitions from constituent assets can be detected by
            iterating over the instruments in the portfolio and checking each individually.
        """
        return None

    def generate_weights(
        self,
        instruments: List[str],
        returns_history: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date
    ) -> Dict[str, float]:
        """
        Generate optimal portfolio weights using Grinold-Kahn framework.

        Workflow:
            1. Calculate signals (Z-scores) for each instrument
            2. Convert Z-scores → alphas (expected returns) via IC × Vol × Z
            3. Estimate covariance matrix from returns history
            4. Optimize portfolio: max α'w - λ/2 × w'Σw
            5. Return optimal weights

        Args:
            instruments: List of instrument identifiers
            returns_history: Historical returns (DataFrame: rows=dates, cols=instruments)
            market_data: Market data provider (optional, needed by some signals)
            as_of: Current date for signal calculation

        Returns:
            Dict mapping instrument → weight (summing to 1.0)

        Example:
            >>> returns = pl.DataFrame({
            ...     'SFRZ4': [0.01, -0.01, 0.02, ...],
            ...     'SFRH5': [0.005, -0.005, 0.01, ...]
            ... })
            >>> weights = portfolio.generate_weights(
            ...     instruments=['SFRZ4', 'SFRH5'],
            ...     returns_history=returns,
            ...     market_data=mdp,
            ...     as_of=date(2024, 11, 1)
            ... )
            >>> weights
            {'SFRZ4': 0.65, 'SFRH5': 0.35}
        """
        # Step 1: Calculate signals (Z-scores)
        signal_scores = self._aggregate_signals(instruments, market_data, as_of)

        # Step 2: Convert signals → alphas (expected returns)
        alphas = self.alpha_generator.signals_to_alphas(
            signals=signal_scores,
            returns_history=returns_history,
            as_of=as_of
        )

        # Step 3: Estimate covariance matrix
        cov_matrix = self.risk_model.fit(returns_history)

        # Step 4: Optimize portfolio
        # Get column names (polars returns list)
        column_order = returns_history.columns
        weights = self._optimize_portfolio(alphas, cov_matrix, column_order)

        # Update state
        self.current_weights = weights
        self.last_rebalance = as_of

        return weights

    def _aggregate_signals(
        self,
        instruments: List[str],
        market_data: Optional[Any],
        as_of: date
    ) -> Dict[str, float]:
        """
        Aggregate multiple signals into combined Z-scores.

        For multiple signals, we average their Z-scores:
            combined_z = mean(z_1, z_2, ..., z_n)

        Args:
            instruments: List of instruments
            market_data: Market data provider
            as_of: Calculation date

        Returns:
            Dict mapping instrument → combined Z-score

        Note:
            This is a simple equal-weight combination.
            More sophisticated approaches (IC-weighted, orthogonalized)
            can be implemented via SignalCombiner.
        """
        if not self.signals:
            return {inst: 0.0 for inst in instruments}

        # Calculate each signal
        all_scores = []
        for signal in self.signals:
            try:
                scores = signal.calculate(instruments, market_data, as_of)
                all_scores.append(scores)
            except Exception as e:
                # Handle signal calculation failure gracefully
                print(f"Warning: Signal {signal.name} failed: {e}")
                continue

        if not all_scores:
            return {inst: 0.0 for inst in instruments}

        # Average signals (equal weight)
        combined = {}
        for inst in instruments:
            signal_values = [scores.get(inst, 0.0) for scores in all_scores]
            combined[inst] = np.mean(signal_values)

        return combined

    def _optimize_portfolio(
        self,
        alphas: Dict[str, float],
        cov_matrix: np.ndarray,
        column_order: List[str]
    ) -> Dict[str, float]:
        """
        Optimize portfolio given alphas and covariance.

        Solves:
            max α'w - λ/2 × w'Σw
            subject to: sum(w) = 1, optional constraints

        Args:
            alphas: Expected returns for each asset
            cov_matrix: Covariance matrix (N×N)
            column_order: Order of columns in cov_matrix

        Returns:
            Dict mapping asset → weight

        Note:
            This handles the array ordering carefully to ensure alphas
            and covariance matrix are aligned correctly.
        """
        # Get assets in correct order
        assets = list(alphas.keys())

        # Extract covariance submatrix for these assets
        # Find indices of assets in the original column_order
        asset_indices = [column_order.index(asset) for asset in assets]

        # Extract submatrix using numpy indexing
        cov_sub = cov_matrix[np.ix_(asset_indices, asset_indices)]

        # Convert alphas dict and covariance to polars for optimizer
        # Create polars Series with alphas values (optimizer gets asset names from covariance DataFrame)
        alpha_values = [alphas[asset] for asset in assets]
        alpha_series = pl.Series(name='alpha', values=alpha_values, dtype=pl.Float64)

        # Create polars DataFrame for covariance submatrix with asset names as columns
        cov_dict = {asset: cov_sub[i, :].tolist() for i, asset in enumerate(assets)}
        cov_sub_df = pl.DataFrame(cov_dict)

        # Optimize (returns dict)
        weights = self.optimizer.optimize(alpha_series, cov_sub_df)

        return weights

    def calculate_return(
        self,
        returns: Dict[str, float],
        weights: Optional[Dict[str, float]] = None,
        **kwargs
    ) -> float:
        """
        Calculate portfolio return from constituent returns.

        Formula:
            r_portfolio = Σ(w_i × r_i)

        Args:
            returns: Realized returns for each asset (decimal, e.g., 0.01 = 1%)
            weights: Portfolio weights (decimal, e.g., 0.6 = 60%)
                     If None, uses self.current_weights from last rebalance
            **kwargs: Additional arguments (for compatibility with Asset interface)

        Returns:
            Portfolio return (decimal)

        Raises:
            ValueError: If weights is None and no current_weights exist

        Example:
            With explicit weights:
            >>> weights = {'SFRZ4': 0.6, 'SFRH5': 0.4}
            >>> returns = {'SFRZ4': 0.02, 'SFRH5': 0.01}
            >>> port_return = portfolio.calculate_return(returns, weights)
            >>> port_return
            0.016  # 1.6%

            Using current weights:
            >>> # After generate_weights has been called
            >>> returns = {'SFRZ4': 0.02, 'SFRH5': 0.01}
            >>> port_return = portfolio.calculate_return(returns)

        Note:
            This method handles missing assets gracefully by treating
            missing returns as 0.0.
        """
        # Use provided weights or fall back to current weights
        weights_to_use = weights if weights is not None else self.current_weights

        if weights_to_use is None:
            raise ValueError(
                "No weights provided and no current_weights exist. "
                "Call generate_weights() first or provide explicit weights."
            )

        portfolio_return = 0.0

        for asset, weight in weights_to_use.items():
            asset_return = returns.get(asset, 0.0)
            portfolio_return += weight * asset_return

        return portfolio_return

    def should_rebalance(self, as_of: date) -> bool:
        """
        Determine if portfolio should rebalance on given date.

        Args:
            as_of: Current date

        Returns:
            True if should rebalance, False otherwise

        Note:
            Currently implements simple frequency-based rebalancing.
            Could be extended to include:
            - Threshold-based rebalancing (weight drift)
            - Signal-based rebalancing (regime changes)
            - Transaction cost-aware rebalancing
        """
        if self.last_rebalance is None:
            return True

        days_since_rebalance = (as_of - self.last_rebalance).days

        if self.rebalance_frequency == 'daily':
            return days_since_rebalance >= 1
        elif self.rebalance_frequency == 'weekly':
            return days_since_rebalance >= 7
        elif self.rebalance_frequency == 'monthly':
            return days_since_rebalance >= 30
        else:
            return False

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"GrinoldKahnPortfolio(identifier='{self.identifier}', "
            f"signals={len(self.signals)}, "
            f"IC={self.alpha_generator.IC:.3f}, "
            f"rebalance='{self.rebalance_frequency}')"
        )
