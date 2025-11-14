"""
Tests for QuerySignal bridge adapter.

Test coverage:
1. Construction and validation
2. Query execution via MDP
3. Value extraction
4. Standardization
5. Caching behavior
6. Integration with AlphaGenerator
"""

import pytest
import polars as pl
import numpy as np
from datetime import date
from unittest.mock import Mock, MagicMock

from Signals.Bridges.QuerySignal import QuerySignal
from Query.Base.BaseQuery import BaseQuery
from MDP.MarketDataProvider import MarketDataProvider


class MockQuery(BaseQuery):
    """Mock query for testing."""

    def __init__(self, value_to_return=1.0):
        super().__init__()
        self.value_to_return = value_to_return

    def return_query(self):
        return self

    def col_name(self, cube_name=None):
        return "mock"

    def eval_expression(self, cube_name=None):
        return "mock"


class TestQuerySignalConstruction:
    """Test QuerySignal initialization and validation."""

    def test_construction_with_minimal_args(self):
        """QuerySignal constructs with query and MDP."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        signal = QuerySignal(query=query, mdp=mdp)

        assert signal.query is query
        assert signal.mdp is mdp
        assert signal.value_field is None
        assert signal.standardize is True
        assert signal.cache_results is True

    def test_construction_with_all_args(self):
        """QuerySignal accepts all optional parameters."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        signal = QuerySignal(
            query=query,
            mdp=mdp,
            value_field='carry',
            standardize=False,
            cache_results=False
        )

        assert signal.query is query
        assert signal.mdp is mdp
        assert signal.value_field == 'carry'
        assert signal.standardize is False
        assert signal.cache_results is False

    def test_none_query_raises_error(self):
        """None query raises ValueError."""
        mdp = Mock(spec=MarketDataProvider)

        with pytest.raises(ValueError, match="query cannot be None"):
            QuerySignal(query=None, mdp=mdp)

    def test_none_mdp_raises_error(self):
        """None MDP raises ValueError."""
        query = MockQuery()

        with pytest.raises(ValueError, match="mdp cannot be None"):
            QuerySignal(query=query, mdp=None)

    def test_signal_name_uses_query_product(self):
        """Signal name incorporates query product."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        signal = QuerySignal(query=query, mdp=mdp)

        # MockQuery has product="" by default
        assert "QuerySignal" in signal.name


class TestQueryExecution:
    """Test query execution via MDP."""

    def test_executes_query_via_mdp(self):
        """QuerySignal executes query through MDP.get_pricer()."""
        query = MockQuery(value_to_return=5.0)
        mdp = Mock(spec=MarketDataProvider)

        # Create mock pricer and value map
        mock_pricer = Mock()
        mock_value_map = Mock()
        mock_value_map.apply.return_value = 5.0

        mdp.get_pricer.return_value = mock_pricer

        # Mock query methods
        query.resolve_package = Mock(return_value=([Mock()], [1.0]))
        query.build_value_map = Mock(return_value=mock_value_map)
        query.default_mtm_value_id = Mock(return_value='value')

        signal = QuerySignal(query=query, mdp=mdp)

        # Generate signal
        as_of = date(2024, 11, 1)
        inst_data = pl.DataFrame()
        result = signal.generate(inst_data, None, as_of)

        # Verify MDP was called
        assert mdp.get_pricer.called
        assert result == 5.0

    def test_extracts_correct_value_field(self):
        """Extracts specified field from query result."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        # Create mock pricer and value map
        mock_pricer = Mock()
        mock_value_map = Mock()
        mock_value_map.apply.return_value = 10.0

        mdp.get_pricer.return_value = mock_pricer

        # Mock query methods
        query.resolve_package = Mock(return_value=([Mock()], [1.0]))
        query.build_value_map = Mock(return_value=mock_value_map)

        signal = QuerySignal(query=query, mdp=mdp, value_field='carry')

        # Generate signal
        as_of = date(2024, 11, 1)
        result = signal.generate(pl.DataFrame(), None, as_of)

        # Verify value_field was used
        mock_value_map.apply.assert_called_with(value='carry')
        assert result == 10.0

    def test_uses_default_value_id_when_no_field_specified(self):
        """Uses query.default_mtm_value_id() when value_field is None."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        # Create mock pricer and value map
        mock_pricer = Mock()
        mock_value_map = Mock()
        mock_value_map.apply.return_value = 7.5

        mdp.get_pricer.return_value = mock_pricer

        # Mock query methods
        query.resolve_package = Mock(return_value=([Mock()], [1.0]))
        query.build_value_map = Mock(return_value=mock_value_map)
        query.default_mtm_value_id = Mock(return_value='default_value')

        signal = QuerySignal(query=query, mdp=mdp)  # No value_field

        # Generate signal
        as_of = date(2024, 11, 1)
        result = signal.generate(pl.DataFrame(), None, as_of)

        # Verify default was used
        query.default_mtm_value_id.assert_called_once()
        mock_value_map.apply.assert_called_with(value='default_value')


class TestErrorHandling:
    """Test error handling."""

    def test_handles_value_extraction_failure(self):
        """Returns 0.0 when value extraction fails."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        # Create mock pricer and value map that raises exception
        mock_pricer = Mock()
        mock_value_map = Mock()
        mock_value_map.apply.side_effect = Exception("Value extraction failed")

        mdp.get_pricer.return_value = mock_pricer

        # Mock query methods
        query.resolve_package = Mock(return_value=([Mock()], [1.0]))
        query.build_value_map = Mock(return_value=mock_value_map)
        query.default_mtm_value_id = Mock(return_value='value')

        signal = QuerySignal(query=query, mdp=mdp)

        # Generate signal - should not raise, returns 0.0
        as_of = date(2024, 11, 1)
        result = signal.generate(pl.DataFrame(), None, as_of)

        assert result == 0.0


class TestCaching:
    """Test MDP result caching."""

    def test_caching_enabled_avoids_duplicate_calls(self):
        """With cache_results=True, doesn't repeat MDP calls."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        # Create mock pricer and value map
        mock_pricer = Mock()
        mock_value_map = Mock()
        mock_value_map.apply.return_value = 3.0

        mdp.get_pricer.return_value = mock_pricer

        # Mock query methods
        query.resolve_package = Mock(return_value=([Mock()], [1.0]))
        query.build_value_map = Mock(return_value=mock_value_map)
        query.default_mtm_value_id = Mock(return_value='value')

        signal = QuerySignal(query=query, mdp=mdp, cache_results=True)

        # Generate signal twice for same date
        as_of = date(2024, 11, 1)
        result1 = signal.generate(pl.DataFrame(), None, as_of)
        result2 = signal.generate(pl.DataFrame(), None, as_of)

        # Should only call MDP once
        assert mdp.get_pricer.call_count == 1
        assert result1 == result2 == 3.0

    def test_caching_disabled_calls_every_time(self):
        """With cache_results=False, calls MDP each time."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        # Create mock pricer and value map
        mock_pricer = Mock()
        mock_value_map = Mock()
        mock_value_map.apply.return_value = 3.0

        mdp.get_pricer.return_value = mock_pricer

        # Mock query methods
        query.resolve_package = Mock(return_value=([Mock()], [1.0]))
        query.build_value_map = Mock(return_value=mock_value_map)
        query.default_mtm_value_id = Mock(return_value='value')

        signal = QuerySignal(query=query, mdp=mdp, cache_results=False)

        # Generate signal twice for same date
        as_of = date(2024, 11, 1)
        result1 = signal.generate(pl.DataFrame(), None, as_of)
        result2 = signal.generate(pl.DataFrame(), None, as_of)

        # Should call MDP twice
        assert mdp.get_pricer.call_count == 2
        assert result1 == result2 == 3.0

    def test_clear_cache_empties_cache(self):
        """clear_cache() empties the cache."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        # Create mock pricer and value map
        mock_pricer = Mock()
        mock_value_map = Mock()
        mock_value_map.apply.return_value = 3.0

        mdp.get_pricer.return_value = mock_pricer

        # Mock query methods
        query.resolve_package = Mock(return_value=([Mock()], [1.0]))
        query.build_value_map = Mock(return_value=mock_value_map)
        query.default_mtm_value_id = Mock(return_value='value')

        signal = QuerySignal(query=query, mdp=mdp, cache_results=True)

        # Generate signal
        as_of = date(2024, 11, 1)
        signal.generate(pl.DataFrame(), None, as_of)

        # Clear cache
        signal.clear_cache()

        # Generate again - should call MDP again
        signal.generate(pl.DataFrame(), None, as_of)
        assert mdp.get_pricer.call_count == 2


class TestRepresentation:
    """Test string representation."""

    def test_repr(self):
        """__repr__ shows configuration."""
        query = MockQuery()
        mdp = Mock(spec=MarketDataProvider)

        signal = QuerySignal(query=query, mdp=mdp, value_field='carry')

        repr_str = repr(signal)
        assert 'QuerySignal' in repr_str
        assert 'carry' in repr_str
