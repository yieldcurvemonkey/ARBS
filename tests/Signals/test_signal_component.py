# ABOUTME: Test suite for SignalComponent abstract base class
# ABOUTME: Validates abstract interface, concrete implementations, and component attributes
import pytest
import polars as pl
import numpy as np
from typing import Dict, Any

from Signals.signal_component import SignalComponent


class MockSignalComponent(SignalComponent):
    """Concrete implementation of SignalComponent for testing."""

    def __init__(self, name: str = "mock_component", metadata: Dict[str, Any] = None):
        """Initialize mock component with simple calculation logic."""
        super().__init__(name=name, metadata=metadata or {})

    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """Simple calculation: multiply all values by 2."""
        return data * 2


class TestSignalComponent:
    """Test suite for SignalComponent base class."""

    def test_calculate_abstract(self):
        """Base class calculate() should raise NotImplementedError."""
        # Cannot instantiate abstract class directly
        with pytest.raises(TypeError):
            SignalComponent(name="test", metadata={})

    def test_concrete_implementation_calculate(self):
        """Mock implementation should return calculated DataFrame."""
        component = MockSignalComponent()
        data = pl.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})

        result = component.calculate(data)

        expected = pl.DataFrame({"a": [2, 4, 6], "b": [8, 10, 12]})
        assert result.frame_equal(expected)

    def test_name_attribute(self):
        """Component should allow setting and getting name."""
        component = MockSignalComponent(name="test_component")

        assert component.name == "test_component"

        # Test default name
        default_component = MockSignalComponent()
        assert default_component.name == "mock_component"

    def test_metadata_attribute(self):
        """Component should allow setting and getting metadata dict."""
        metadata = {"key1": "value1", "key2": 42}
        component = MockSignalComponent(name="test", metadata=metadata)

        assert component.metadata == metadata
        assert component.metadata["key1"] == "value1"
        assert component.metadata["key2"] == 42

    def test_multiple_instances(self):
        """Should be able to create multiple different components."""
        component1 = MockSignalComponent(name="comp1", metadata={"id": 1})
        component2 = MockSignalComponent(name="comp2", metadata={"id": 2})
        component3 = MockSignalComponent(name="comp3", metadata={"id": 3})

        assert component1.name == "comp1"
        assert component2.name == "comp2"
        assert component3.name == "comp3"

        assert component1.metadata["id"] == 1
        assert component2.metadata["id"] == 2
        assert component3.metadata["id"] == 3

    def test_calculate_with_mock_data(self):
        """Calculate should accept and process DataFrame."""
        component = MockSignalComponent()

        # Test with different data shapes
        data1 = pl.DataFrame({"x": [1.0, 2.0, 3.0]})
        result1 = component.calculate(data1)
        assert result1["x"].to_list() == [2.0, 4.0, 6.0]

        data2 = pl.DataFrame({"a": [10], "b": [20], "c": [30]})
        result2 = component.calculate(data2)
        assert result2["a"].to_list() == [20]
        assert result2["b"].to_list() == [40]
        assert result2["c"].to_list() == [60]

    def test_metadata_is_dict(self):
        """Metadata should be a dictionary type."""
        component = MockSignalComponent(metadata={"test": "value"})

        assert isinstance(component.metadata, dict)

        # Test with empty metadata
        empty_component = MockSignalComponent()
        assert isinstance(empty_component.metadata, dict)

    def test_component_immutability(self):
        """Component attributes should be settable but metadata should be independent per instance."""
        metadata1 = {"shared": "value"}
        component1 = MockSignalComponent(name="comp1", metadata=metadata1)
        component2 = MockSignalComponent(name="comp2", metadata={"other": "data"})

        # Modify component1's metadata
        component1.metadata["new_key"] = "new_value"

        # component2's metadata should be unaffected
        assert "new_key" not in component2.metadata
        assert component2.metadata == {"other": "data"}

        # Original dict should be affected (shallow copy behavior)
        assert metadata1["new_key"] == "new_value"
