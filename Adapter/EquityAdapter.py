# ABOUTME: Equity adapter for converting EquityQuery/ETFQuery results into signal-ready DataFrame
# ABOUTME: Fetches prices, calculates returns, and formats with sector/weight for downstream processing
"""
Equity Adapter

Converts EquityQuery and ETFQuery results into signal-ready Polars DataFrame format.

Input:
- List[Union[EquityQuery, ETFQuery]]: Stock/ETF queries
- as_of_date: Valuation date
- YahooFinanceMDP: Source of equity prices and metadata

Output:
- DataFrame with columns:
    - ticker: Ticker symbol (e.g., 'AAPL')
    - date: Trading date
    - close: Closing price (adjusted)
    - return: Simple return (optional, calculated if needed)
    - sector: GICS Level 1 sector
    - weight: Portfolio weight from query

Algorithm:
1. For each query, build MDP request using build_mdp_request()
2. Fetch prices from YahooFinanceMDP
3. Calculate returns from prices if value type is RETURN
4. Merge sector information from query
5. Add weight from query
6. Return consolidated DataFrame with all tickers

Business Logic:
- Returns calculation: Simple returns (pct_change) or log returns
- Missing data: Forward fill (graceful degradation)
- Sector: Taken from query (query is source of truth)
- Weight: Defaults to 1.0 if not specified
"""

from datetime import date
from typing import Any, List, Union
import polars as pl

from Adapter.Base.BaseAdapter import BaseAdapter
from Query.Equities.EquityQuery import EquityQuery
from Query.Equities.ETFQuery import ETFQuery
from Query.Equities.EquityValue import EquityValue


class EquityAdapter(BaseAdapter):
    """
    Adapter for equity and ETF queries.

    Converts EquityQuery/ETFQuery objects into DataFrame format suitable
    for signal generation and portfolio construction.

    Attributes:
        mdp: Market data provider for getting prices and metadata
    """

    def __init__(self, market_data_provider: Any):
        """
        Initialize equity adapter.

        Args:
            market_data_provider: Source of market prices (YahooFinanceMDP)
        """
        super().__init__(market_data_provider)

    def convert(
        self,
        queries: List[Union[EquityQuery, ETFQuery]],
        as_of_date: date,
    ) -> pl.DataFrame:
        """
        Convert equity queries to signal-ready DataFrame.

        Args:
            queries: List of EquityQuery or ETFQuery objects
            as_of_date: Valuation date

        Returns:
            DataFrame with columns:
                - ticker: Ticker symbol
                - date: Trading date
                - close: Closing price
                - return: Simple return (if calculated)
                - sector: GICS sector
                - weight: Portfolio weight

        Example:
            >>> mdp = YahooFinanceMDP()
            >>> adapter = EquityAdapter(mdp)
            >>> queries = [
            ...     EquityQuery(ticker='AAPL', sector='Information Technology', ...),
            ...     EquityQuery(ticker='MSFT', sector='Information Technology', ...),
            ... ]
            >>> df = adapter.convert(queries, date(2024, 6, 15))
            >>> print(df[['ticker', 'date', 'close', 'return', 'sector']])
        """
        if len(queries) == 0:
            # Return empty DataFrame with expected columns
            return pl.DataFrame({
                'ticker': [],
                'date': [],
                'close': [],
                'return': [],
                'sector': [],
                'weight': []
            })

        # Collect all data for each query
        dfs = []
        for query in queries:
            try:
                df = self._convert_single_query(query, as_of_date)
                if df is not None and not df.is_empty():
                    dfs.append(df)
            except Exception as e:
                # Log and continue with other queries
                print(f"Warning: Failed to convert query for {query.ticker}: {e}")
                continue

        if len(dfs) == 0:
            return pl.DataFrame({
                'ticker': [],
                'date': [],
                'close': [],
                'return': [],
                'sector': [],
                'weight': []
            })

        # Concatenate all DataFrames
        result = pl.concat(dfs)
        return result

    def _convert_single_query(
        self,
        query: Union[EquityQuery, ETFQuery],
        as_of_date: date,
    ) -> pl.DataFrame:
        """
        Convert a single equity/ETF query to DataFrame format.

        Args:
            query: EquityQuery or ETFQuery
            as_of_date: Valuation date

        Returns:
            DataFrame with ticker, date, close, return, sector, weight
        """
        # Build MDP request
        mdp_request = query.build_mdp_request(as_of_date)

        # Fetch prices from MDP
        prices_df = self._fetch_prices(mdp_request)

        if prices_df.is_empty():
            return pl.DataFrame({
                'ticker': [],
                'date': [],
                'close': [],
                'return': [],
                'sector': [],
                'weight': []
            })

        # Add ticker if not present
        if 'ticker' not in prices_df.columns:
            prices_df = prices_df.with_columns(
                pl.lit(query.ticker).alias('ticker')
            )

        # Calculate returns if needed
        if query.value in [EquityValue.RETURN, EquityValue.LOG_RETURN]:
            prices_df = self._calculate_returns(
                prices_df,
                return_type=query.value
            )
        elif 'return' not in prices_df.columns:
            # Add null return column if not calculating
            prices_df = prices_df.with_columns(
                pl.lit(None, dtype=pl.Float64).alias('return')
            )

        # Add sector
        prices_df = prices_df.with_columns(
            pl.lit(query.sector).alias('sector')
        )

        # Add weight
        prices_df = prices_df.with_columns(
            pl.lit(query.weight).alias('weight')
        )

        # Select and order columns
        result = prices_df.select([
            'ticker',
            'date',
            'close',
            'return',
            'sector',
            'weight'
        ])

        return result

    def _fetch_prices(self, mdp_request: dict) -> pl.DataFrame:
        """
        Fetch prices from market data provider.

        Args:
            mdp_request: Dictionary with MDP request parameters
                - ticker: str
                - start_date: date
                - end_date: date
                - fields: List[str]
                - adjusted: bool

        Returns:
            DataFrame with date, close (and other price columns)
        """
        ticker = mdp_request['ticker']
        start_date = mdp_request['start_date']
        end_date = mdp_request['end_date']

        try:
            # Try to get prices using the standard MDP interface
            if hasattr(self.mdp, 'get_prices'):
                # Batch-style interface
                prices_df = self.mdp.get_prices(
                    tickers=[ticker],
                    start_date=start_date,
                    end_date=end_date,
                    adjusted=mdp_request.get('adjusted', True)
                )
            elif hasattr(self.mdp, 'get_equity_data'):
                # Unified interface
                prices_df = self.mdp.get_equity_data(
                    tickers=[ticker],
                    start_date=start_date,
                    end_date=end_date,
                    include_fundamentals=False,
                    include_sectors=False,
                )
            else:
                # Fallback: return empty DataFrame
                return pl.DataFrame({
                    'date': [],
                    'close': []
                })

            # Filter to specific ticker if multiple returned
            if 'ticker' in prices_df.columns:
                prices_df = prices_df.filter(pl.col('ticker') == ticker)

            # Ensure we have required columns
            if 'close' not in prices_df.columns:
                if 'Close' in prices_df.columns:
                    prices_df = prices_df.rename({'Close': 'close'})
                else:
                    return pl.DataFrame({
                        'date': [],
                        'close': []
                    })

            if 'date' not in prices_df.columns:
                if 'Date' in prices_df.columns:
                    prices_df = prices_df.rename({'Date': 'date'})

            # Sort by date
            prices_df = prices_df.sort('date')

            return prices_df

        except Exception as e:
            # Graceful degradation: return empty DataFrame
            print(f"Warning: Failed to fetch prices for {ticker}: {e}")
            return pl.DataFrame({
                'date': [],
                'close': []
            })

    def _calculate_returns(
        self,
        df: pl.DataFrame,
        return_type: EquityValue = EquityValue.RETURN,
    ) -> pl.DataFrame:
        """
        Calculate returns from prices.

        Args:
            df: DataFrame with 'close' column
            return_type: RETURN (simple) or LOG_RETURN

        Returns:
            DataFrame with 'return' column added
        """
        if 'close' not in df.columns:
            # No price data, return with null returns
            return df.with_columns(
                pl.lit(None, dtype=pl.Float64).alias('return')
            )

        # Sort by date to ensure proper return calculation
        df = df.sort('date')

        if return_type == EquityValue.RETURN:
            # Simple returns: (P_t - P_{t-1}) / P_{t-1}
            df = df.with_columns(
                pl.col('close').pct_change().alias('return')
            )
        elif return_type == EquityValue.LOG_RETURN:
            # Log returns: log(P_t / P_{t-1})
            df = df.with_columns(
                (pl.col('close') / pl.col('close').shift(1)).log().alias('return')
            )
        else:
            # Unsupported return type, use simple returns
            df = df.with_columns(
                pl.col('close').pct_change().alias('return')
            )

        return df

    def __repr__(self) -> str:
        return f"EquityAdapter(mdp={self.mdp})"
