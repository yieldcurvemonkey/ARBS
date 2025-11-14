# ABOUTME: Generic backtest supporting all asset classes and signal types
# ABOUTME: Configurable components via dependency injection, two workflows (query/DataFrame)

"""
Generic Backtest

Flexible backtest engine supporting:
- Any signal type (carry, momentum, mean reversion, custom)
- Any adapter (futures, equities, custom)
- Multiple signals with combiner
- Query-based workflow (futures, swaps)
- DataFrame-based workflow (equities, ETFs)
- Custom risk models and optimizers

Usage Patterns:

1. Futures Carry (query-based workflow):
   >>> from Backtest.Backtest import Backtest
   >>> from Adapter.FuturesAdapter import FuturesAdapter
   >>> from Signals.Futures.CarrySignal import CarrySignal
   >>>
   >>> backtest = Backtest(
   ...     mdp=market_data_provider,
   ...     adapter=FuturesAdapter(mdp),
   ...     signals=CarrySignal()
   ... )
   >>> result = backtest.run(contracts=['SFRZ4'], dates=[...])

2. Futures Momentum (query-based workflow):
   >>> backtest = Backtest(
   ...     mdp=mdp,
   ...     adapter=FuturesAdapter(mdp),
   ...     signals=MomentumSignal(lookback=20)
   ... )
   >>> result = backtest.run(contracts=['SFRZ4'], dates=[...])

3. Multi-Signal (query-based workflow):
   >>> backtest = Backtest(
   ...     mdp=mdp,
   ...     adapter=FuturesAdapter(mdp),
   ...     signals=[CarrySignal(), MomentumSignal()],
   ...     signal_combiner=SignalCombiner(method='ic_weighted')
   ... )
   >>> result = backtest.run(contracts=['SFRZ4'], dates=[...])

4. Equity/ETF Strategies (DataFrame-based workflow):
   >>> backtest = Backtest(
   ...     signals=VolatilitySignal(),
   ...     risk_aversion=3.0
   ... )
   >>> result = backtest.run_from_dataframe(returns_df, dates=[...])

Component Injection:
- All components are configurable
- Sensible defaults provided
- Easy for simple cases, flexible for advanced
"""

from datetime import date
from typing import Any, List, Optional, Union
import numpy as np
import polars as pl

from Backtest.Base.BaseBacktest import BaseBacktest, BacktestResult
from Signals.Base.BaseSignal import BaseSignal
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Risk.Returns.ReturnsCalculator import ReturnsCalculator
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer
from Query.Base.BaseQuery import BaseQuery


class Backtest(BaseBacktest):
    """
    Generic backtest with configurable components.

    Supports two workflows:
    1. Query-based: mdp + adapter + contracts → run()
    2. DataFrame-based: returns_df → run_from_dataframe()
    """

    def __init__(
        self,
        # Data source (query workflow)
        mdp: Optional[Any] = None,
        adapter: Optional[Any] = None,  # BaseAdapter

        # Signals (signal workflow)
        signals: Optional[Union[BaseSignal, List[BaseSignal]]] = None,
        signal_combiner: Optional[Any] = None,  # SignalCombiner

        # Queries (query workflow)
        queries: Optional[List[BaseQuery]] = None,
        triggers: Optional[List[Any]] = None,

        # Pipeline components (optional)
        alpha_generator: Optional[AlphaGenerator] = None,
        risk_model: Optional[Any] = None,
        optimizer: Optional[Any] = None,
        returns_calculator: Optional[ReturnsCalculator] = None,

        # Convenience parameters
        IC: float = 0.05,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        min_history: int = 20,
    ):
        """
        Initialize generic backtest with component injection.

        Supports THREE workflows:
        1. Signal-driven (existing): Provide signals
        2. Query-driven (NEW): Provide mdp + queries
        3. Hybrid (NEW): Provide both signals and queries

        Args:
            mdp: Market data provider (for query workflow)
            adapter: Converts queries → DataFrame (FuturesAdapter, EquityAdapter)
            signals: Single signal or list of signals to combine
            signal_combiner: How to combine multiple signals
            queries: List of queries to execute (query workflow)
            triggers: Event triggers (query workflow)
            alpha_generator: Converts signals → expected returns
            risk_model: Covariance estimator
            optimizer: Portfolio weight optimizer
            returns_calculator: Price → return conversion
            IC: Information coefficient (if using default alpha_generator)
            risk_aversion: Risk aversion parameter (if using default optimizer)
            long_only: Only long positions (if using default optimizer)
            min_history: Minimum periods for covariance estimation

        Raises:
            ValueError: If neither signals nor queries provided
            ValueError: If using adapter without mdp
            ValueError: If using queries without mdp
        """
        # Call parent
        super().__init__(mdp)

        # Detect workflow
        self._workflow = self._detect_workflow(signals, mdp, queries)

        # Validate based on workflow
        if self._workflow == 'signal':
            # Signal workflow: signals required
            if signals is None:
                raise ValueError("Signal workflow requires signals")
        elif self._workflow == 'query':
            # Query workflow: mdp + queries required
            if mdp is None:
                raise ValueError("Query workflow requires mdp")
            if queries is None:
                raise ValueError("Query workflow requires queries")
        elif self._workflow == 'hybrid':
            # Hybrid: both required
            if mdp is None:
                raise ValueError("Hybrid workflow requires mdp")

        # Validate: Adapter requires mdp
        if adapter is not None and mdp is None:
            raise ValueError("Adapter requires mdp to be provided")

        # Store configuration
        self.adapter = adapter
        self.min_history = min_history

        # Store query workflow components
        self.queries = queries or []
        self.triggers = triggers or []

        # Handle signals (convert single to list)
        if isinstance(signals, BaseSignal):
            self.signals = [signals]
        else:
            self.signals = signals if signals else []

        # Create signal combiner if multiple signals
        if len(self.signals) > 1:
            if signal_combiner is None:
                # Import here to avoid circular dependency
                from Signals.SignalCombiner import SignalCombiner
                self.signal_combiner = SignalCombiner()
            else:
                self.signal_combiner = signal_combiner
        else:
            self.signal_combiner = signal_combiner  # None for single signal

        # Create or use provided components
        self.alpha_generator = alpha_generator or AlphaGenerator(IC=IC)
        self.risk_model = risk_model or LedoitWolfShrinkage()
        self.optimizer = optimizer or MeanVarianceOptimizer(
            risk_aversion=risk_aversion,
            long_only=long_only,
        )
        self.returns_calc = returns_calculator or ReturnsCalculator(method="percent")

    def _detect_workflow(self, signals, mdp, queries) -> str:
        """
        Detect which workflow to use based on parameters.

        Returns:
            'signal': Signal-driven workflow
            'query': Query-driven workflow
            'hybrid': Both workflows
        """
        has_signals = signals is not None
        has_queries = mdp is not None and queries is not None

        if has_signals and has_queries:
            return 'hybrid'
        elif has_queries:
            return 'query'
        elif has_signals:
            return 'signal'
        else:
            raise ValueError("Must provide either signals or (mdp + queries)")

    def run(
        self,
        contracts: List[str] = None,
        dates: List[date] = None,
        time_grid: List[date] = None,
        **kwargs
    ) -> BacktestResult:
        """
        Run backtest using detected workflow.

        Routes to:
        - run() with adapter for signal workflow (existing)
        - run_from_queries() for query workflow (NEW)

        Args:
            contracts: List of contract codes (signal workflow with adapter)
            dates: List of rebalance dates (signal workflow)
            time_grid: List of dates (query workflow)
            **kwargs: Additional arguments

        Returns:
            BacktestResult with performance metrics

        Raises:
            ValueError: If required parameters missing for detected workflow
        """
        # Route based on workflow
        if self._workflow == 'query':
            # Query workflow: use time_grid or dates
            grid = time_grid if time_grid is not None else dates
            if grid is None:
                raise ValueError("Query workflow requires time_grid or dates")
            return self.run_from_queries(time_grid=grid, **kwargs)
        elif self._workflow in ('signal', 'hybrid'):
            # Signal workflow: continue with existing logic
            return self._run_signal_workflow(contracts=contracts, dates=dates)
        else:
            raise ValueError(f"Unknown workflow: {self._workflow}")

    def _run_signal_workflow(
        self,
        contracts: List[str],
        dates: List[date],
    ) -> BacktestResult:
        """
        Run backtest using signal-based workflow (existing implementation).

        Requires: self.mdp and self.adapter

        Args:
            contracts: List of contract codes (e.g., ['SFRZ4', 'SFRH5'])
            dates: List of rebalance dates

        Returns:
            BacktestResult with performance metrics

        Raises:
            ValueError: If adapter or mdp not provided
        """
        # Validate workflow requirements
        if self.adapter is None or self.mdp is None:
            raise ValueError(
                "Signal workflow with adapter requires adapter and mdp. "
                "Use run_from_dataframe() for DataFrame-based workflow without adapter."
            )

        if len(contracts) == 0 or len(dates) == 0:
            return self._empty_result()

        # Import Query classes (adapter-specific, but common pattern)
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure

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

            # Step 2: Generate signals using configured signal(s)
            if len(self.signals) == 1:
                # Single signal - call generate() per instrument
                signals = {}
                if isinstance(df, pl.DataFrame):
                    row_iter = df.iter_rows(named=True)
                else:
                    row_iter = (row for _, row in df.iterrows())

                for row in row_iter:
                    contract = row['contract']
                    # Create single-row DataFrame for this instrument
                    if isinstance(df, pl.DataFrame):
                        inst_df = df.filter(pl.col('contract') == contract)
                    else:
                        inst_df = df[df['contract'] == contract]
                    # Generate signal for this instrument
                    try:
                        signal_value = self.signals[0].generate(inst_df, self.mdp, as_of)
                        signals[contract] = signal_value
                    except Exception:
                        signals[contract] = 0.0
            else:
                # Multiple signals: generate each and combine
                # First, generate signals for all instruments with each signal
                individual_signals = []
                for sig in self.signals:
                    sig_dict = {}
                    if isinstance(df, pl.DataFrame):
                        row_iter = df.iter_rows(named=True)
                    else:
                        row_iter = (row for _, row in df.iterrows())

                    for row in row_iter:
                        contract = row['contract']
                        if isinstance(df, pl.DataFrame):
                            inst_df = df.filter(pl.col('contract') == contract)
                        else:
                            inst_df = df[df['contract'] == contract]
                        try:
                            signal_value = sig.generate(inst_df, self.mdp, as_of)
                            sig_dict[contract] = signal_value
                        except Exception:
                            sig_dict[contract] = 0.0
                    individual_signals.append(sig_dict)

                # Combine signals
                if self.signal_combiner is not None:
                    # Convert list of dicts to Dict[signal_name, signal_dict]
                    signals_dict = {
                        sig.name: sig_values
                        for sig, sig_values in zip(self.signals, individual_signals)
                    }
                    signals = self.signal_combiner.combine(signals_dict, method='equal')
                else:
                    # Fallback: equal weight combination
                    signals = {}
                    for sig_dict in individual_signals:
                        for contract, value in sig_dict.items():
                            signals[contract] = signals.get(contract, 0.0) + value / len(individual_signals)

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
            dates_list = list(returns_dict.keys())
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

    def run_from_dataframe(
        self,
        returns_df: pl.DataFrame,
        dates: List[date],
        instruments: Optional[List[str]] = None,
    ) -> BacktestResult:
        """
        Run backtest from pre-computed returns DataFrame.

        No adapter needed - returns already provided.

        Args:
            returns_df: DataFrame with ['date', 'ticker', 'return']
            dates: List of rebalance dates
            instruments: Tickers to trade (optional)

        Returns:
            BacktestResult with performance metrics

        Raises:
            ValueError: If adapter is set (shouldn't use adapter with DataFrame workflow)
        """
        # Validate
        if self.adapter is not None:
            raise ValueError(
                "DataFrame workflow doesn't use adapter. "
                "Use run() for query-based workflow."
            )

        if len(dates) == 0:
            return self._empty_result()

        # Filter instruments if provided
        if instruments is not None:
            returns_df = returns_df.filter(pl.col('ticker').is_in(instruments))

        # Storage for results
        all_weights = []
        all_signals = []
        all_returns = []

        # Track return history for covariance estimation
        return_history = []

        previous_weights = None

        for i, as_of in enumerate(dates):
            # Ensure as_of is a date object
            if hasattr(as_of, 'date'):
                as_of = as_of.date()

            # Get returns for this date
            date_returns = returns_df.filter(pl.col('date') == as_of)

            if len(date_returns) == 0:
                continue

            # Convert to dict {ticker: return}
            returns_dict = {
                row['ticker']: row['return']
                for row in date_returns.iter_rows(named=True)
            }

            # Track return history
            return_history.append(returns_dict)

            # Calculate portfolio return if we have previous weights
            if previous_weights is not None:
                common_tickers = list(set(returns_dict.keys()) & set(previous_weights.keys()))
                if len(common_tickers) > 0:
                    port_ret = sum(previous_weights[t] * returns_dict[t] for t in common_tickers)
                    all_returns.append({'date': as_of, 'return': port_ret})

            # Step 1: Generate signals using configured signal(s)
            # Signals work on returns DataFrame
            if len(self.signals) == 1:
                # Single signal - call generate() per instrument
                signals = {}
                for row in date_returns.iter_rows(named=True):
                    ticker = row['ticker']
                    # Create single-row DataFrame for this ticker
                    inst_df = date_returns.filter(pl.col('ticker') == ticker)
                    # Generate signal for this ticker
                    try:
                        signal_value = self.signals[0].generate(inst_df, None, as_of)
                        signals[ticker] = signal_value
                    except Exception:
                        signals[ticker] = 0.0
            else:
                # Multiple signals: generate each and combine
                individual_signals = []
                for sig in self.signals:
                    sig_dict = {}
                    for row in date_returns.iter_rows(named=True):
                        ticker = row['ticker']
                        inst_df = date_returns.filter(pl.col('ticker') == ticker)
                        try:
                            signal_value = sig.generate(inst_df, None, as_of)
                            sig_dict[ticker] = signal_value
                        except Exception:
                            sig_dict[ticker] = 0.0
                    individual_signals.append(sig_dict)

                # Combine signals
                if self.signal_combiner is not None:
                    # Convert list of dicts to Dict[signal_name, signal_dict]
                    signals_dict = {
                        sig.name: sig_values
                        for sig, sig_values in zip(self.signals, individual_signals)
                    }
                    signals = self.signal_combiner.combine(signals_dict, method='equal')
                else:
                    # Fallback: equal weight combination
                    signals = {}
                    for sig_dict in individual_signals:
                        for ticker, value in sig_dict.items():
                            signals[ticker] = signals.get(ticker, 0.0) + value / len(individual_signals)

            if len(signals) == 0:
                tickers = list(returns_dict.keys())
                signals = {t: 0.0 for t in tickers}

            all_signals.append({'date': as_of, **signals})

            # Step 2: Estimate covariance (if we have enough history)
            if len(return_history) >= self.min_history:
                hist_df = pl.DataFrame(return_history).fill_null(0)
                cov_matrix = self.risk_model.fit(hist_df)
            else:
                # Not enough history: use identity
                cov_matrix = np.eye(len(signals)) * 0.01

            # Step 3: Convert signals → alphas
            signal_values = list(signals.values())
            if np.std(signal_values) > 0:
                mean_sig = np.mean(signal_values)
                std_sig = np.std(signal_values)
                z_scores = {t: (signals[t] - mean_sig) / std_sig for t in signals.keys()}
            else:
                z_scores = signals

            # Convert z-scores → alphas
            if len(return_history) > 0:
                hist_df = pl.DataFrame(return_history).fill_null(0)
                alphas = self.alpha_generator.signals_to_alphas(z_scores, hist_df, as_of)
            else:
                alphas = z_scores

            # Step 4: Optimize weights
            try:
                weights = self.optimizer.optimize(alphas, cov_matrix)
                all_weights.append({'date': as_of, **weights})
                previous_weights = weights
            except Exception:
                # Optimization failed: use equal weights
                equal_weights = {t: 1.0 / len(alphas) for t in alphas.keys()}
                all_weights.append({'date': as_of, **equal_weights})
                previous_weights = equal_weights

        # Convert to DataFrames
        weights_df = pl.DataFrame(all_weights).fill_null(0) if all_weights else pl.DataFrame()
        signals_df = pl.DataFrame(all_signals).fill_null(0) if all_signals else pl.DataFrame()

        # Convert returns to series
        if all_returns:
            values = [r['return'] for r in all_returns]
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
            prices=pl.DataFrame(),  # No prices in DataFrame workflow
            ic=ic,
            sharpe_ratio=sharpe,
            total_return=total_return,
        )

    def run_from_queries(
        self,
        time_grid: List[date],
        **kwargs
    ) -> BacktestResult:
        """
        Run backtest using query-driven workflow.

        Executes queries via MDP at each time step.

        Args:
            time_grid: List of dates for query execution
            **kwargs: Additional arguments

        Returns:
            BacktestResult with performance metrics

        Raises:
            ValueError: If mdp or queries not provided
        """
        # Validate workflow requirements
        if self.mdp is None or len(self.queries) == 0:
            raise ValueError(
                "Query workflow requires mdp and queries. "
                "Use run() or run_from_dataframe() for signal-based workflow."
            )

        if len(time_grid) == 0:
            return self._empty_result()

        # Storage for results
        all_positions = []
        all_returns = []
        mtm_history = {}

        previous_mtm = 0.0

        for i, as_of in enumerate(time_grid):
            # Ensure as_of is a date object
            if hasattr(as_of, 'date'):
                as_of = as_of.date()

            # Execute queries via MDP
            import datetime
            now = datetime.datetime.combine(as_of, datetime.time())

            # Calculate MTM for current positions
            current_mtm = 0.0
            for query in self.queries:
                try:
                    # Build MDP request
                    mdp_request = query.build_mdp_request(now)
                    pricer_or_curve = self.mdp.get_pricer(mdp_request)

                    # Resolve package
                    package, weights = query.resolve_package(pricer_or_curve=pricer_or_curve)

                    # Build value map
                    value_map = query.build_value_map(
                        pricer_or_curve=pricer_or_curve,
                        package=package,
                        risk_weights=weights
                    )

                    # Get MTM value
                    value_id = query.default_mtm_value_id()
                    if value_id is not None:
                        mtm_value = float(value_map.apply(value=value_id))
                        current_mtm += mtm_value
                except Exception as e:
                    # Handle query execution failures gracefully
                    continue

            mtm_history[as_of] = current_mtm

            # Calculate return from MTM change
            if i > 0:
                if previous_mtm != 0:
                    period_return = (current_mtm - previous_mtm) / abs(previous_mtm)
                else:
                    period_return = 0.0
                all_returns.append({'date': as_of, 'return': period_return})

            previous_mtm = current_mtm

        # Convert returns to series
        if all_returns:
            values = [r['return'] for r in all_returns]
            returns_series = pl.Series(values=values)
        else:
            returns_series = pl.Series(values=[], dtype=pl.Float64)

        # Calculate performance metrics
        sharpe = self._calculate_sharpe(returns_series)
        total_return = self._calculate_total_return(returns_series)

        return BacktestResult(
            weights=pl.DataFrame(),  # Query workflow doesn't track weights
            returns=returns_series,
            signals=pl.DataFrame(),  # No signals in pure query workflow
            prices=pl.DataFrame(),
            ic=np.nan,  # IC not applicable for query workflow
            sharpe_ratio=sharpe,
            total_return=total_return,
        )

    def _calculate_ic(self, signals: pl.DataFrame, returns: pl.Series) -> float:
        """Calculate Information Coefficient."""
        if len(returns) < 2:
            return np.nan

        # For IC, we need to align signals with future returns
        try:
            from Signals.Utils.IC import calculate_ic

            # Get signal values (flatten across instruments)
            if len(signals) > 0:
                signal_values = signals.to_numpy().flatten()
            else:
                signal_values = []

            if len(signal_values) > 0 and len(returns) > 0:
                return_values = returns.to_numpy()
                # Align lengths
                min_len = min(len(signal_values), len(return_values))
                return calculate_ic(signal_values[:min_len], return_values[:min_len])
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
        signal_names = [s.name for s in self.signals]
        return (
            f"Backtest("
            f"signals={signal_names}, "
            f"adapter={self.adapter.__class__.__name__ if self.adapter else None})"
        )
