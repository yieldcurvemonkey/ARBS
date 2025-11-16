# ABOUTME: Adapter converting BaseQuery to BaseSignal interface (extends BaseSignal)
# ABOUTME: Enables derivative queries to generate signals for portfolio optimization

"""
QuerySignal - Query to Signal Bridge

Adapts BaseQuery (derivative pricing) to BaseSignal (alpha generation) interface.
Enables using derivative queries as signals in Grinold-Kahn portfolio optimization.

Example:
    >>> from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    >>> from Query.IRSwaps.IRSwapValue import IRSwapValue
    >>> from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    >>>
    >>> # Create query that computes swap carry
    >>> carry_query = IRSwapQuery(
    ...     value=IRSwapValue.CARRY,
    ...     tenor="5Y",
    ...     curve="USD-SOFR-1D"
    ... )
    >>>
    >>> # Wrap as signal
    >>> carry_signal = QuerySignal(
    ...     query=carry_query,
    ...     mdp=IRSwapsMDP(),
    ...     value_field='carry'  # Extract this field from query result
    ... )
    >>>
    >>> # Use in backtest like any other signal
    >>> backtest = Backtest(signals=carry_signal)
"""

from typing import Dict, Any, Optional
import polars as pl
import numpy as np
from datetime import date

from Signals.Base.BaseSignal import BaseSignal
from Query.Base.BaseQuery import BaseQuery
from MDP.MarketDataProvider import MarketDataProvider


class QuerySignal(BaseSignal):
    """
    Adapter that executes queries via MDP and extracts signal values.

    Workflow:
    1. Execute query via MDP at as_of date
    2. Extract value from query result using value_field
    3. Standardize to z-scores (if requested)
    4. Return as signal compatible with AlphaGenerator
    """

    def __init__(
        self,
        query: BaseQuery,
        mdp: MarketDataProvider,
        value_field: Optional[str] = None,
        standardize: bool = True,
        cache_results: bool = True
    ):
        """
        Initialize QuerySignal adapter.

        Args:
            query: BaseQuery instance to execute
            mdp: MarketDataProvider for market data
            value_field: Field to extract from query result (e.g., 'carry', 'rate', 'spread')
                        If None, uses query.default_mtm_value_id()
            standardize: Whether to z-score the values
            cache_results: Whether to cache MDP calls

        Raises:
            ValueError: If query or mdp is None
        """
        if query is None:
            raise ValueError("query cannot be None")
        if mdp is None:
            raise ValueError("mdp cannot be None")

        # Initialize base signal
        super().__init__(
            name=f"QuerySignal({query.product})",
            standardize=standardize,
            track_history=True
        )

        self.query = query
        self.mdp = mdp
        self.value_field = value_field
        self.cache_results = cache_results
        self._cache: Dict[date, float] = {}

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date
    ) -> float:
        """
        Calculate signal by executing query via MDP.

        Args:
            inst_data: Instrument-specific data (not used for query-based signals)
            market_data: Market data provider (uses self.mdp)
            as_of: Date for signal generation

        Returns:
            Raw signal value from query execution
        """
        # Check cache first
        if self.cache_results and as_of in self._cache:
            return self._cache[as_of]

        # Build MDP request for this date
        import datetime
        now = datetime.datetime.combine(as_of, datetime.time())
        mdp_request = self.query.build_mdp_request(now)

        # Get pricer from MDP
        pricer_or_curve = self.mdp.get_pricer(mdp_request)

        # Resolve query package
        package, weights = self.query.resolve_package(pricer_or_curve=pricer_or_curve)

        # Build value map
        value_map = self.query.build_value_map(
            pricer_or_curve=pricer_or_curve,
            package=package,
            risk_weights=weights
        )

        # Determine which value to extract
        if self.value_field is not None:
            value_id = self.value_field
        else:
            # Use query's default MTM value
            value_id = self.query.default_mtm_value_id()

        # Extract value
        try:
            signal_value = float(value_map.apply(value=value_id))
        except Exception as e:
            # If value extraction fails, return 0
            print(f"Warning: Failed to extract value '{value_id}' from query: {e}")
            signal_value = 0.0

        # Cache result
        if self.cache_results:
            self._cache[as_of] = signal_value

        return signal_value

    def clear_cache(self) -> None:
        """Clear the MDP result cache."""
        self._cache.clear()

    def __repr__(self) -> str:
        return (
            f"QuerySignal("
            f"query={self.query.product}, "
            f"value_field={self.value_field}, "
            f"standardize={self.standardize})"
        )
