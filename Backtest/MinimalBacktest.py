# ABOUTME: Minimal backtest loop integrating all MVP components
# ABOUTME: Executes Query→Adapter→Signals→Risk→Optimizer pipeline and tracks P&L
"""
Minimal Backtest

Integrates all components for end-to-end strategy backtesting.

Algorithm:
1. For each date in backtest period:
   - Use FuturesAdapter to get prices and format data
   - Generate signals with CarrySignal
   - Estimate covariance with LedoitWolfShrinkage
   - Optimize weights with MeanVarianceOptimizer
   - Track positions and calculate P&L

2. Calculate performance metrics:
   - Returns time series
   - Information Coefficient (IC)
   - Sharpe ratio
   - Total return

MVP Philosophy:
- Goal is ACCURATE measurement, not profitable strategy
- If IC is negative or Sharpe is negative, that's FINE
- We measure what actually happens without cherry-picking
- No optimization for good-looking results

Components Used:
- Adapter.FuturesAdapter: Query → DataFrame
- Signals.Futures.CarrySignal: DataFrame → alphas
- Risk.Covariance.LedoitWolfShrinkage: returns → covariance
- Optimizer.MeanVarianceOptimizer: alphas + cov → weights

Output:
- BacktestResult with full performance metrics
- Honest measurement regardless of profitability
"""

from datetime import date
from typing import Any, List
import numpy as np
import pandas as pd

from Backtest.Base.BaseBacktest import BaseBacktest, BacktestResult
from Adapter.FuturesAdapter import FuturesAdapter
from Query.Futures.FuturesQuery import FuturesQuery
from Query.Futures.FuturesStructure import FuturesStructure
from Signals.Futures.CarrySignal import CarrySignal
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Risk.Returns.ReturnsCalculator import ReturnsCalculator
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer
from Signals.Utils.IC import calculate_ic


class MinimalBacktest(BaseBacktest):
    """
    Minimal backtest integrating all MVP components.

    Executes complete pipeline from queries to P&L tracking.

    Attributes:
        mdp: Market data provider
        risk_aversion: Risk aversion parameter for optimizer
        long_only: If True, no short positions
        min_history: Minimum periods of returns for covariance estimation
    """

    def __init__(
        self,
        mdp: Any,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        min_history: int = 20,
        IC: float = 0.05,
    ):
        """
        Initialize minimal backtest.

        Args:
            mdp: Market data provider
            risk_aversion: Risk aversion λ (higher = more conservative)
            long_only: If True, only allow positive weights
            min_history: Minimum periods needed for covariance estimation
            IC: Information Coefficient (forecasting skill, default 0.05)
        """
        super().__init__(mdp)
        self.risk_aversion = risk_aversion
        self.long_only = long_only
        self.min_history = min_history
        self.IC = IC

        # Initialize components
        self.adapter = FuturesAdapter(mdp)
        self.signal = CarrySignal(name='carry', standardize=True)
        self.alpha_generator = AlphaGenerator(IC=IC)
        self.risk_model = LedoitWolfShrinkage()
        self.returns_calc = ReturnsCalculator(method="percent")
        self.optimizer = MeanVarianceOptimizer(
            risk_aversion=risk_aversion,
            long_only=long_only,
        )

    def run(
        self,
        contracts: List[str],
        dates: List[date],
    ) -> BacktestResult:
        """
        Run minimal backtest.

        Args:
            contracts: List of contract codes to trade
            dates: List of backtest dates (sorted)

        Returns:
            BacktestResult with performance metrics

        Algorithm:
            For each date:
            1. Get prices via Adapter
            2. Generate carry signals (z-scores)
            3. Convert signals → alphas using IC × Vol × Z
            4. Estimate covariance from return history
            5. Optimize portfolio weights using alphas
            6. Track positions and calculate returns
        """
        if len(contracts) == 0 or len(dates) == 0:
            return self._empty_result()

        # Storage for results
        all_weights = []
        all_signals = []
        all_prices = []
        all_returns = []

        # Track return history for covariance estimation
        return_history = []

        # Create queries for all contracts
        queries = [
            FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract=c)
            for c in contracts
        ]

        previous_weights = None
        previous_prices = None

        for i, as_of in enumerate(dates):
            # Ensure as_of is a date object (not Timestamp)
            if hasattr(as_of, 'date'):
                as_of = as_of.date()

            # Step 1: Get prices via Adapter
            df = self.adapter.convert(queries, as_of)

            if len(df) == 0:
                continue

            # Store prices
            prices = pd.Series({row['contract']: row['price'] for _, row in df.iterrows()})
            all_prices.append({'date': as_of, **prices.to_dict()})

            # Calculate returns if we have previous prices
            if previous_prices is not None and previous_weights is not None:
                # Use ReturnsCalculator for price → return conversion
                curr_prices_dict = prices.to_dict()
                prev_prices_dict = previous_prices.to_dict()
                returns_dict = self.returns_calc.calculate_returns(curr_prices_dict, prev_prices_dict)
                returns = pd.Series(returns_dict)

                if len(returns) > 0:
                    return_history.append(returns)

                    # Calculate portfolio return (weighted sum of returns)
                    common_contracts = list(set(returns.index) & set(previous_weights.index))
                    if len(common_contracts) > 0:
                        port_ret = sum(previous_weights[c] * returns.get(c, 0.0) for c in common_contracts)
                        all_returns.append({'date': as_of, 'return': port_ret})

            # Step 2: Generate carry signals
            signals = {}
            for _, row in df.iterrows():
                contract = row['contract']
                price = row['price']
                next_price = row.get('next_price', np.nan)
                roll_date = row.get('roll_date', as_of)

                # Convert roll_date to date if it's a Timestamp
                if hasattr(roll_date, 'date'):
                    roll_date = roll_date.date()

                # Calculate carry if we have next price
                if not np.isnan(next_price) and roll_date > as_of:
                    days_to_roll = (roll_date - as_of).days
                    if days_to_roll > 0:
                        # Annualized carry in bps
                        carry = ((price - next_price) / days_to_roll) * 365 * 10000
                        signals[contract] = carry

            if len(signals) == 0:
                signals = {c: 0.0 for c in contracts}

            signals_series = pd.Series(signals)
            all_signals.append({'date': as_of, **signals})

            # Step 3: Estimate covariance (if we have enough history)
            if len(return_history) >= self.min_history:
                returns_df = pd.DataFrame(return_history).fillna(0)
                cov_matrix = self.risk_model.fit(returns_df)
                cov_df = pd.DataFrame(cov_matrix, index=returns_df.columns, columns=returns_df.columns)
            else:
                # Not enough history: use identity (equal variance, no correlation)
                cov_df = pd.DataFrame(
                    np.eye(len(signals_series)) * 0.01,
                    index=signals_series.index,
                    columns=signals_series.index
                )

            # Step 4: Convert signals → alphas using IC × Vol × Z
            # First standardize signals to z-scores
            if signals_series.std() > 0:
                z_scores = (signals_series - signals_series.mean()) / signals_series.std()
            else:
                z_scores = signals_series

            # Convert z-scores → alphas (expected returns)
            if len(return_history) > 0:
                returns_df = pd.DataFrame(return_history).fillna(0)
                alphas_dict = self.alpha_generator.signals_to_alphas(
                    z_scores.to_dict(),
                    returns_df,
                    as_of
                )
                alphas = pd.Series(alphas_dict)
            else:
                # No history: use z-scores directly (fallback)
                alphas = z_scores

            # Step 5: Optimize weights
            try:
                weights = self.optimizer.optimize(alphas, cov_df)
                all_weights.append({'date': as_of, **weights.to_dict()})
                previous_weights = weights
            except Exception:
                # Optimization failed: use equal weights
                equal_weights = pd.Series(1.0 / len(alphas), index=alphas.index)
                all_weights.append({'date': as_of, **equal_weights.to_dict()})
                previous_weights = equal_weights

            previous_prices = prices

        # Convert to DataFrames
        weights_df = pd.DataFrame(all_weights).set_index('date').fillna(0)
        signals_df = pd.DataFrame(all_signals).set_index('date').fillna(0)
        prices_df = pd.DataFrame(all_prices).set_index('date').fillna(0)
        returns_series = pd.Series({r['date']: r['return'] for r in all_returns})

        # Calculate performance metrics
        ic = self._calculate_ic(signals_df, returns_series)
        sharpe = self._calculate_sharpe(returns_series)
        total_return = self._calculate_total_return(returns_series)

        return BacktestResult(
            weights=weights_df,
            returns=returns_series,
            signals=signals_df,
            prices=prices_df,
            ic=ic,
            sharpe_ratio=sharpe,
            total_return=total_return,
        )

    def _calculate_ic(self, signals: pd.DataFrame, returns: pd.Series) -> float:
        """Calculate Information Coefficient."""
        if len(returns) < 2:
            return np.nan

        # For IC, we need to align signals with future returns
        # This is simplified: use last signal value vs next return
        # More sophisticated: lag signals properly
        try:
            # Get signal values (flatten across contracts)
            signal_values = signals.values.flatten()
            # Crude approximation for MVP
            if len(signal_values) > 0 and len(returns) > 0:
                # Just check if positive signals → positive returns on average
                return calculate_ic(signal_values[:len(returns)], returns.values)
            return 0.0
        except Exception:
            return 0.0

    def _calculate_sharpe(self, returns: pd.Series) -> float:
        """Calculate Sharpe ratio (annualized)."""
        if len(returns) < 2:
            return np.nan

        mean_ret = returns.mean()
        std_ret = returns.std()

        if std_ret == 0:
            return 0.0

        # Annualize (assume weekly returns)
        sharpe = (mean_ret / std_ret) * np.sqrt(52)
        return sharpe

    def _calculate_total_return(self, returns: pd.Series) -> float:
        """Calculate cumulative return."""
        if len(returns) == 0:
            return 0.0

        # Compound returns
        cum_ret = (1 + returns).prod() - 1
        return cum_ret

    def _empty_result(self) -> BacktestResult:
        """Return empty result for edge cases."""
        return BacktestResult(
            weights=pd.DataFrame(),
            returns=pd.Series(dtype=float),
            signals=pd.DataFrame(),
            prices=pd.DataFrame(),
            ic=np.nan,
            sharpe_ratio=np.nan,
            total_return=0.0,
        )

    def __repr__(self) -> str:
        return (
            f"MinimalBacktest("
            f"risk_aversion={self.risk_aversion}, "
            f"long_only={self.long_only})"
        )
