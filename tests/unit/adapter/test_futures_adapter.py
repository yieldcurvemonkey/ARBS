# ABOUTME: Test suite for FuturesAdapter (Query → Signals bridge)
# ABOUTME: Verifies conversion from FuturesQuery → DataFrame format for signal consumption
"""
Tests for FuturesAdapter

Verifies the adapter layer that bridges Query and Signals:
- Takes FuturesQuery + market data → produces signal-ready DataFrame
- Handles calendar spreads (front/back prices)
- Handles roll dates
- Works with multiple contracts

MVP Goal: Measure correctly, not necessarily positive IC
- Output format should be correct
- Prices should be reasonable
- Roll dates should be calculated
- If the strategy loses money, that's fine - we measure it accurately
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta


class TestFuturesAdapterBasics:
    """Test basic adapter functionality."""

    def test_adapter_can_be_imported(self):
        """Verify FuturesAdapter exists and can be imported."""
        from Adapter.FuturesAdapter import FuturesAdapter
        assert FuturesAdapter is not None

    def test_adapter_can_be_instantiated(self, mock_mdp):
        """Adapter can be created with market data provider."""
        from Adapter.FuturesAdapter import FuturesAdapter

        adapter = FuturesAdapter(mock_mdp)

        assert adapter is not None
        assert adapter.mdp == mock_mdp

    def test_adapter_has_convert_method(self, mock_mdp):
        """Adapter has convert() method for Query → DataFrame."""
        from Adapter.FuturesAdapter import FuturesAdapter

        adapter = FuturesAdapter(mock_mdp)
        assert hasattr(adapter, 'convert')


class TestSingleContractConversion:
    """Test conversion for single futures contract."""

    def test_single_outright_contract(self, mock_mdp):
        """Single outright contract → DataFrame with price and expiry."""
        from Adapter.FuturesAdapter import FuturesAdapter
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure

        adapter = FuturesAdapter(mock_mdp)

        # Single contract
        queries = [
            FuturesQuery(
                structure=FuturesStructure.OUTRIGHT,
                contract='SFRZ4',
            )
        ]

        as_of = date(2024, 6, 15)
        df = adapter.convert(queries, as_of)

        # Should have one row
        assert len(df) == 1
        assert 'SFRZ4' in df['contract'].values

        # Should have price
        assert 'price' in df.columns
        assert df.loc[0, 'price'] > 0

        # Should have expiry (roll date)
        assert 'roll_date' in df.columns
        assert isinstance(df.loc[0, 'roll_date'], date)

    def test_multiple_outright_contracts(self, mock_mdp):
        """Multiple outright contracts → DataFrame with multiple rows."""
        from Adapter.FuturesAdapter import FuturesAdapter
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure

        adapter = FuturesAdapter(mock_mdp)

        # Multiple contracts
        contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
        queries = [
            FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract=c)
            for c in contracts
        ]

        as_of = date(2024, 6, 15)
        df = adapter.convert(queries, as_of)

        # Should have 3 rows
        assert len(df) == 3

        # All contracts present
        assert set(df['contract']) == set(contracts)


class TestOutputFormat:
    """Test that output format is correct for signals."""

    def test_output_has_required_columns(self, mock_mdp):
        """Output DataFrame has all required columns for signal generation."""
        from Adapter.FuturesAdapter import FuturesAdapter
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure

        adapter = FuturesAdapter(mock_mdp)

        queries = [FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract='SFRZ4')]
        as_of = date(2024, 6, 15)
        df = adapter.convert(queries, as_of)

        # Required columns for carry signal
        required_cols = ['contract', 'price', 'next_contract', 'next_price', 'roll_date']
        for col in required_cols:
            assert col in df.columns, f"Missing column: {col}"

    def test_prices_are_reasonable(self, mock_mdp):
        """Prices are in reasonable range (not NaN, not negative)."""
        from Adapter.FuturesAdapter import FuturesAdapter
        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure

        adapter = FuturesAdapter(mock_mdp)

        queries = [FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract='SFRZ4')]
        as_of = date(2024, 6, 15)
        df = adapter.convert(queries, as_of)

        # Price should be reasonable for SOFR futures (90-100 range typically)
        price = df.loc[0, 'price']
        assert not np.isnan(price)
        assert 85.0 < price < 105.0  # Wide range to allow for various market conditions


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_query_list(self, mock_mdp):
        """Empty query list → empty DataFrame."""
        from Adapter.FuturesAdapter import FuturesAdapter

        adapter = FuturesAdapter(mock_mdp)

        as_of = date(2024, 6, 15)
        df = adapter.convert([], as_of)

        # Should return empty DataFrame with correct columns
        assert len(df) == 0
        assert 'contract' in df.columns
        assert 'price' in df.columns
