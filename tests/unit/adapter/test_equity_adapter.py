# ABOUTME: Test suite for EquityAdapter (Query → Signals bridge)
# ABOUTME: Verifies conversion from EquityQuery/ETFQuery → DataFrame format for signal consumption
"""
Tests for EquityAdapter

Verifies the adapter layer that bridges Query and Signals:
- Takes EquityQuery/ETFQuery + market data → produces signal-ready DataFrame
- Calculates returns from prices
- Handles sector classification
- Works with multiple tickers

MVP Goal: Measure correctly, not necessarily positive IC
- Output format should be correct
- Prices should be reasonable
- Returns should be calculated properly
- If the strategy loses money, that's fine - we measure it accurately
"""

import pytest
import numpy as np
import polars as pl
from datetime import date, timedelta
from unittest.mock import Mock


class MockYahooFinanceMDP:
    """Mock market data provider for testing."""

    def __init__(self):
        self.prices_data = {}

    def add_price_data(self, ticker: str, dates: list, prices: list):
        """Add mock price data for a ticker."""
        self.prices_data[ticker] = pl.DataFrame({
            'ticker': [ticker] * len(dates),
            'date': dates,
            'close': prices,
        })

    def get_prices(
        self,
        tickers: list,
        start_date: date,
        end_date: date,
        adjusted: bool = True,
    ) -> pl.DataFrame:
        """Return mock price data."""
        dfs = []
        for ticker in tickers:
            if ticker in self.prices_data:
                df = self.prices_data[ticker]
                # Filter by date range
                df = df.filter(
                    (pl.col('date') >= start_date) &
                    (pl.col('date') <= end_date)
                )
                dfs.append(df)

        if dfs:
            return pl.concat(dfs)
        else:
            return pl.DataFrame({
                'ticker': [],
                'date': [],
                'close': [],
            })


class TestEquityAdapterBasics:
    """Test basic adapter functionality."""

    def test_adapter_can_be_imported(self):
        """Verify EquityAdapter exists and can be imported."""
        from Adapter.EquityAdapter import EquityAdapter
        assert EquityAdapter is not None

    def test_adapter_can_be_instantiated(self):
        """Adapter can be created with market data provider."""
        from Adapter.EquityAdapter import EquityAdapter

        mdp = MockYahooFinanceMDP()
        adapter = EquityAdapter(mdp)

        assert adapter is not None
        assert adapter.mdp == mdp

    def test_adapter_has_convert_method(self):
        """Adapter has convert() method for Query → DataFrame."""
        from Adapter.EquityAdapter import EquityAdapter

        mdp = MockYahooFinanceMDP()
        adapter = EquityAdapter(mdp)
        assert hasattr(adapter, 'convert')


class TestSingleEquityConversion:
    """Test conversion for single equity query."""

    def test_single_equity_query(self):
        """Single equity query → DataFrame with prices and returns."""
        from Adapter.EquityAdapter import EquityAdapter
        from Query.Equities.EquityQuery import EquityQuery
        from Query.Equities.EquityStructure import EquityStructure
        from Query.Equities.EquityValue import EquityValue

        # Setup mock MDP with price data
        mdp = MockYahooFinanceMDP()
        dates = [date(2024, 1, i) for i in range(1, 11)]
        prices = [100.0 + i for i in range(10)]  # 100, 101, 102, ..., 109
        mdp.add_price_data('AAPL', dates, prices)

        adapter = EquityAdapter(mdp)

        # Single equity query
        queries = [
            EquityQuery(
                ticker='AAPL',
                sector='Information Technology',
                structure=EquityStructure.SINGLE,
                value=EquityValue.RETURN,
                lookback_days=30,
                weight=1.0,
            )
        ]

        as_of = date(2024, 1, 10)
        df = adapter.convert(queries, as_of)

        # Should have multiple rows (time series)
        assert len(df) > 0
        assert 'AAPL' in df['ticker'].to_list()

        # Should have required columns
        assert 'ticker' in df.columns
        assert 'date' in df.columns
        assert 'close' in df.columns
        assert 'return' in df.columns
        assert 'sector' in df.columns
        assert 'weight' in df.columns

        # Check sector and weight
        assert df[0, 'sector'] == 'Information Technology'
        assert df[0, 'weight'] == 1.0

    def test_multiple_equity_queries(self):
        """Multiple equity queries → DataFrame with multiple tickers."""
        from Adapter.EquityAdapter import EquityAdapter
        from Query.Equities.EquityQuery import EquityQuery
        from Query.Equities.EquityStructure import EquityStructure
        from Query.Equities.EquityValue import EquityValue

        # Setup mock MDP with price data for multiple tickers
        mdp = MockYahooFinanceMDP()
        dates = [date(2024, 1, i) for i in range(1, 6)]

        mdp.add_price_data('AAPL', dates, [100, 101, 102, 103, 104])
        mdp.add_price_data('MSFT', dates, [200, 202, 204, 206, 208])

        adapter = EquityAdapter(mdp)

        # Multiple queries
        queries = [
            EquityQuery(
                ticker='AAPL',
                sector='Information Technology',
                structure=EquityStructure.SINGLE,
                value=EquityValue.RETURN,
                lookback_days=10,
            ),
            EquityQuery(
                ticker='MSFT',
                sector='Information Technology',
                structure=EquityStructure.SINGLE,
                value=EquityValue.RETURN,
                lookback_days=10,
            ),
        ]

        as_of = date(2024, 1, 5)
        df = adapter.convert(queries, as_of)

        # Should have rows for both tickers
        assert len(df) > 0
        tickers = df['ticker'].unique().to_list()
        assert 'AAPL' in tickers
        assert 'MSFT' in tickers


class TestETFConversion:
    """Test conversion for ETF queries."""

    def test_etf_query(self):
        """ETF query → DataFrame with prices and returns."""
        from Adapter.EquityAdapter import EquityAdapter
        from Query.Equities.ETFQuery import ETFQuery
        from Query.Equities.EquityValue import EquityValue

        # Setup mock MDP
        mdp = MockYahooFinanceMDP()
        dates = [date(2024, 1, i) for i in range(1, 6)]
        mdp.add_price_data('XLK', dates, [150, 151, 152, 153, 154])

        adapter = EquityAdapter(mdp)

        # ETF query
        queries = [
            ETFQuery(
                ticker='XLK',
                sector='Information Technology',
                value=EquityValue.RETURN,
                lookback_days=10,
            )
        ]

        as_of = date(2024, 1, 5)
        df = adapter.convert(queries, as_of)

        # Should have data
        assert len(df) > 0
        assert 'XLK' in df['ticker'].to_list()
        assert df[0, 'sector'] == 'Information Technology'


class TestReturnCalculation:
    """Test return calculation logic."""

    def test_simple_returns_calculated(self):
        """Simple returns are calculated correctly from prices."""
        from Adapter.EquityAdapter import EquityAdapter
        from Query.Equities.EquityQuery import EquityQuery
        from Query.Equities.EquityStructure import EquityStructure
        from Query.Equities.EquityValue import EquityValue

        # Setup mock MDP with known prices
        mdp = MockYahooFinanceMDP()
        dates = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
        prices = [100.0, 110.0, 121.0]  # 10% and 10% returns
        mdp.add_price_data('TEST', dates, prices)

        adapter = EquityAdapter(mdp)

        queries = [
            EquityQuery(
                ticker='TEST',
                sector='Test',
                structure=EquityStructure.SINGLE,
                value=EquityValue.RETURN,
                lookback_days=10,
            )
        ]

        as_of = date(2024, 1, 3)
        df = adapter.convert(queries, as_of)

        # Check returns (first return should be null, then ~10%, then ~10%)
        returns = df['return'].to_list()
        assert returns[0] is None or np.isnan(returns[0])  # First return is null
        assert abs(returns[1] - 0.10) < 0.001  # 10% return
        assert abs(returns[2] - 0.10) < 0.001  # 10% return


class TestEmptyData:
    """Test handling of empty data and edge cases."""

    def test_empty_queries_list(self):
        """Empty queries list → empty DataFrame."""
        from Adapter.EquityAdapter import EquityAdapter

        mdp = MockYahooFinanceMDP()
        adapter = EquityAdapter(mdp)

        df = adapter.convert([], date(2024, 1, 1))

        assert df.is_empty()
        assert 'ticker' in df.columns
        assert 'date' in df.columns

    def test_query_with_no_data(self):
        """Query for ticker with no data → continue with other queries."""
        from Adapter.EquityAdapter import EquityAdapter
        from Query.Equities.EquityQuery import EquityQuery
        from Query.Equities.EquityStructure import EquityStructure
        from Query.Equities.EquityValue import EquityValue

        # Setup MDP with data for only one ticker
        mdp = MockYahooFinanceMDP()
        dates = [date(2024, 1, i) for i in range(1, 6)]
        mdp.add_price_data('AAPL', dates, [100, 101, 102, 103, 104])
        # No data for 'INVALID'

        adapter = EquityAdapter(mdp)

        queries = [
            EquityQuery(
                ticker='AAPL',
                sector='Information Technology',
                structure=EquityStructure.SINGLE,
                value=EquityValue.RETURN,
                lookback_days=10,
            ),
            EquityQuery(
                ticker='INVALID',
                sector='Unknown',
                structure=EquityStructure.SINGLE,
                value=EquityValue.RETURN,
                lookback_days=10,
            ),
        ]

        as_of = date(2024, 1, 5)
        df = adapter.convert(queries, as_of)

        # Should have data for AAPL only
        assert len(df) > 0
        tickers = df['ticker'].unique().to_list()
        assert 'AAPL' in tickers
        assert 'INVALID' not in tickers
