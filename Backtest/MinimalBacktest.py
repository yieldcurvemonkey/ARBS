# ABOUTME: Minimal backtest loop integrating all MVP components
# ABOUTME: Executes Query→Adapter→Signals→Risk→Optimizer pipeline and tracks P&L
"""
Minimal Backtest

NOTE: For new code, prefer Backtest.Backtest which supports:
- Any signal type (not just carry)
- Any adapter (futures, equities, custom)
- Multiple signals with combiner
- DataFrame-based workflow for equities

MinimalBacktest is specific to futures carry strategies.

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
import polars as pl

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
            if isinstance(df, pl.DataFrame):
                prices = {row['contract']: row['price'] for row in df.iter_rows(named=True)}
            else:
                prices = {row['contract']: row['price'] for _, row in df.iterrows()}
            all_prices.append({'date': as_of, **prices})

            # Calculate returns if we have previous prices
            if previous_prices is not None and previous_weights is not None:
                # Use ReturnsCalculator for price → return conversion
                returns_dict = self.returns_calc.calculate_returns(prices, previous_prices)

                if len(returns_dict) > 0:
                    return_history.append(returns_dict)

                    # Calculate portfolio return (weighted sum of returns)
                    common_contracts = list(set(returns_dict.keys()) & set(previous_weights.keys()))
                    if len(common_contracts) > 0:
                        port_ret = sum(previous_weights[c] * returns_dict.get(c, 0.0) for c in common_contracts)
                        all_returns.append({'date': as_of, 'return': port_ret})

            # Step 2: Generate carry signals
            signals = {}
            if isinstance(df, pl.DataFrame):
                row_iter = df.iter_rows(named=True)
            else:
                row_iter = (row for _, row in df.iterrows())

            for row in row_iter:
                contract = row['contract']
                price = row['price']
                # Handle both pandas and polars row access
                if isinstance(df, pl.DataFrame):
                    next_price = row.get('next_price') or np.nan
                    roll_date = row.get('roll_date') or as_of
                else:
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

            all_signals.append({'date': as_of, **signals})

            # Step 3: Estimate covariance (if we have enough history)
            if len(return_history) >= self.min_history:
                returns_df = pl.DataFrame(return_history).fill_null(0)
                cov_matrix = self.risk_model.fit(returns_df)
            else:
                # Not enough history: use identity (equal variance, no correlation)
                cov_matrix = np.eye(len(signals)) * 0.01

            # Step 4: Convert signals → alphas using IC × Vol × Z
            # First standardize signals to z-scores
            signal_values = list(signals.values())
            if np.std(signal_values) > 0:
                mean_sig = np.mean(signal_values)
                std_sig = np.std(signal_values)
                z_scores = {c: (signals[c] - mean_sig) / std_sig for c in signals.keys()}
            else:
                z_scores = signals

            # Convert z-scores → alphas (expected returns)
            if len(return_history) > 0:
                returns_df = pl.DataFrame(return_history).fill_null(0)
                alphas_dict = self.alpha_generator.signals_to_alphas(
                    z_scores,
                    returns_df,
                    as_of
                )
                alphas = alphas_dict
            else:
                # No history: use z-scores directly (fallback)
                alphas = z_scores

            # Step 5: Optimize weights
            try:
                weights = self.optimizer.optimize(alphas, cov_matrix)
                all_weights.append({'date': as_of, **weights})
                previous_weights = weights
            except Exception:
                # Optimization failed: use equal weights
                equal_weights = {c: 1.0 / len(alphas) for c in alphas.keys()}
                all_weights.append({'date': as_of, **equal_weights})
                previous_weights = equal_weights

            previous_prices = prices

        # Convert to DataFrames
        weights_df = pl.DataFrame(all_weights).fill_null(0) if all_weights else pl.DataFrame()
        signals_df = pl.DataFrame(all_signals).fill_null(0) if all_signals else pl.DataFrame()
        prices_df = pl.DataFrame(all_prices).fill_null(0) if all_prices else pl.DataFrame()
        # Convert returns dict to pl.Series
        returns_dict = {r['date']: r['return'] for r in all_returns}
        if returns_dict:
            dates = list(returns_dict.keys())
            values = list(returns_dict.values())
            returns_series = pl.Series(values=values)
        else:
            returns_series = pl.Series(values=[], dtype=pl.Float64)

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

    def _calculate_ic(self, signals: pl.DataFrame, returns: pl.Series) -> float:
        """Calculate Information Coefficient."""
        if len(returns) < 2:
            return np.nan

        # For IC, we need to align signals with future returns
        # This is simplified: use last signal value vs next return
        # More sophisticated: lag signals properly
        try:
            # Get signal values (flatten across contracts)
            if len(signals) > 0:
                signal_values = signals.to_numpy().flatten()
            else:
                signal_values = []
            # Crude approximation for MVP
            if len(signal_values) > 0 and len(returns) > 0:
                return_values = returns.to_numpy()
                # Just check if positive signals → positive returns on average
                return calculate_ic(signal_values[:len(return_values)], return_values)
            return 0.0
        except Exception:
            return 0.0

    def _calculate_sharpe(self, returns: pl.Series) -> float:
        """Calculate Sharpe ratio (annualized)."""
        if len(returns) < 2:
            return np.nan

        return_values = returns.to_numpy()
        mean_ret = np.mean(return_values)
        std_ret = np.std(return_values)

        if std_ret == 0:
            return 0.0

        # Annualize (assume weekly returns)
        sharpe = (mean_ret / std_ret) * np.sqrt(52)
        return sharpe

    def _calculate_total_return(self, returns: pl.Series) -> float:
        """Calculate cumulative return."""
        if len(returns) == 0:
            return 0.0

        # Compound returns
        return_values = returns.to_numpy()
        cum_ret = np.prod(1 + return_values) - 1
        return cum_ret

    def _empty_result(self) -> BacktestResult:
        """Return empty result for edge cases."""
        return BacktestResult(
            weights=pl.DataFrame(),
            returns=pl.Series(values=[], dtype=pl.Float64),
            signals=pl.DataFrame(),
            prices=pl.DataFrame(),
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
