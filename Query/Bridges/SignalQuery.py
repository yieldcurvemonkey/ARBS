# ABOUTME: Adapter converting BaseSignal to BaseQuery interface
# ABOUTME: Enables signal-based strategies to use query-driven backtest infrastructure

"""
SignalQuery - Signal to Query Bridge

Adapts BaseSignal (alpha generation) to BaseQuery (derivative pricing) interface.
Enables using signals in query-driven backtests.

Example:
    >>> from Signals.Futures.CarrySignal import CarrySignal
    >>> from Query.Bridges.SignalQuery import SignalQuery
    >>>
    >>> # Create signal
    >>> carry_signal = CarrySignal()
    >>>
    >>> # Wrap as query
    >>> carry_query = SignalQuery(
    ...     signal=carry_signal,
    ...     tickers=['AAPL', 'GOOGL', 'MSFT']
    ... )
    >>>
    >>> # Use in query-driven backtest
    >>> from BT.query_engine import QueryDrivenBacktest
    >>> backtest = QueryDrivenBacktest(queries=[carry_query])
"""

from typing import List, Tuple, Callable, Any, Dict, Optional, Union
from dataclasses import dataclass, field
from datetime import date, datetime
import polars as pl
import numpy as np

from Query.Base.BaseQuery import BaseQuery
from Query.Base._GenericPricable import _GenericPricable
from Signals.Base.BaseSignal import BaseSignal


# Default pricable for signal-based positions
@dataclass(frozen=True)
class SignalPosition(_GenericPricable):
    """Simple pricable representing a signal-based position."""
    ticker: str
    signal_value: float


@dataclass(frozen=True)
class SignalQuery(BaseQuery):
    """
    Adapter that generates signals and converts them to query positions.

    Workflow:
    1. Generate signals for all tickers using BaseSignal
    2. Convert signals to positions using position_builder
    3. Return (package, weights) for query-driven backtest

    Attributes:
        signal: BaseSignal instance to execute
        tickers: List of tickers to generate signals for
        position_builder: Function (ticker, signal_value) -> (package, weights)
    """

    signal: BaseSignal = field(default=None)
    tickers: List[str] = field(default_factory=list)
    position_builder: Optional[Callable[[str, float], Tuple[List[_GenericPricable], List[float]]]] = None

    # Override BaseQuery fields
    product: str = field(init=False, default="Signal")

    def __post_init__(self):
        """Validate construction parameters."""
        if self.signal is None:
            raise ValueError("signal cannot be None")
        if not self.tickers or len(self.tickers) == 0:
            raise ValueError("tickers cannot be empty")

        # Set default position builder if not provided
        if self.position_builder is None:
            object.__setattr__(self, 'position_builder', self._default_position_builder)

    @staticmethod
    def _default_position_builder(ticker: str, signal_value: float) -> Tuple[List[_GenericPricable], List[float]]:
        """
        Default position builder that creates one position per ticker.

        Args:
            ticker: Ticker symbol
            signal_value: Signal value (used as position weight)

        Returns:
            (package, weights) tuple
        """
        return [SignalPosition(ticker=ticker, signal_value=signal_value)], [signal_value]

    def _generate_signals(self, as_of: date) -> np.ndarray:
        """
        Generate signals for all tickers.

        Args:
            as_of: Date for signal generation

        Returns:
            Array of signal values (one per ticker)
        """
        # Create empty DataFrames for each ticker (signals may not need data)
        inst_data_list = [pl.DataFrame({"ticker": [ticker]}) for ticker in self.tickers]

        # Generate batch signals
        signals = self.signal.generate_batch(
            inst_data_list=inst_data_list,
            market_data=None,  # Signal-based, no market data needed
            as_of=as_of
        )

        return signals

    def _build_positions(
        self,
        tickers: List[str],
        signals: np.ndarray
    ) -> Tuple[List[_GenericPricable], List[float]]:
        """
        Build positions from signals using position_builder.

        Args:
            tickers: List of ticker symbols
            signals: Array of signal values

        Returns:
            (package, weights) tuple for all positions
        """
        all_package = []
        all_weights = []

        for ticker, signal_value in zip(tickers, signals):
            package, weights = self.position_builder(ticker, float(signal_value))
            all_package.extend(package)
            all_weights.extend(weights)

        return all_package, all_weights

    def build_mdp_request(self, now: datetime) -> Dict[str, Any]:
        """
        Build MDP request for market data.

        Signal-based queries typically don't need MDP, so this returns
        an empty dict unless market_request was explicitly provided.

        Args:
            now: Current timestamp

        Returns:
            MDP request dict
        """
        # Return market_request if provided, otherwise empty dict
        return dict(self.market_request or {})

    def resolve_package(
        self,
        *,
        pricer_or_curve: Any,
        **hints: Any
    ) -> Tuple[List[_GenericPricable], List[float]]:
        """
        Resolve query into package of positions + weights.

        Args:
            pricer_or_curve: Market data (not used for signal-based queries)
            **hints: Additional parameters (may include 'as_of' date)

        Returns:
            (package, weights) tuple
        """
        # Extract as_of date from hints or use today
        as_of = hints.get('as_of', date.today())

        # Generate signals for all tickers
        signals = self._generate_signals(as_of=as_of)

        # Build positions from signals
        package, weights = self._build_positions(self.tickers, signals)

        return package, weights

    def return_query(self) -> Union["BaseQuery", List["BaseQuery"]]:
        """
        Return query for position tracking.

        Returns:
            Self (single query)
        """
        return self

    def col_name(self, cube_name: Optional[str] = None) -> str:
        """
        Generate column name for this query.

        Args:
            cube_name: Optional cube identifier

        Returns:
            Column name string
        """
        base_name = self.name or f"{self.signal.name}_{len(self.tickers)}tickers"
        if cube_name:
            return f"{cube_name}_{base_name}"
        return base_name

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        """
        Generate evaluation expression for this query.

        Args:
            cube_name: Optional cube identifier

        Returns:
            Expression string
        """
        return self.col_name(cube_name)

    def __repr__(self) -> str:
        return (
            f"SignalQuery("
            f"signal={self.signal.name}, "
            f"tickers={len(self.tickers)}, "
            f"name={self.name})"
        )
