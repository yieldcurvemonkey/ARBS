# ABOUTME: Tests for DecomposableSignal abstract base class that combines multiple signal components
# ABOUTME: Validates abstract method enforcement, component composition, and weighting strategies

import pytest
import pandas as pd
import numpy as np
from abc import ABC
from Signals.decomposable_signal import DecomposableSignal


class MockDecomposableSignal(DecomposableSignal):
    """Concrete implementation for testing DecomposableSignal"""

    def __init__(self, components_dict, component_weights=None):
        """
        Args:
            components_dict: Dict of component name -> DataFrame
            component_weights: Optional dict of component name -> weight
        """
        self._components = components_dict
        super().__init__(component_weights=component_weights)

    def get_components(self):
        """Return mock components"""
        return self._components


class TestDecomposableSignal:
    """Test suite for DecomposableSignal abstract base class"""

    def test_get_components_abstract(self):
        """Base class get_components() must be abstract and raise NotImplementedError"""
        # Cannot instantiate abstract class directly
        with pytest.raises(TypeError):
            DecomposableSignal()

    def test_concrete_implementation_components(self):
        """Concrete implementation should return components dict"""
        dates = pd.date_range('2020-01-01', periods=5)
        assets = ['ES', 'TY']

        comp_a = pd.DataFrame(
            np.random.randn(5, 2),
            index=dates,
            columns=assets
        )
        comp_b = pd.DataFrame(
            np.random.randn(5, 2),
            index=dates,
            columns=assets
        )

        signal = MockDecomposableSignal({
            'component_a': comp_a,
            'component_b': comp_b
        })

        components = signal.get_components()
        assert isinstance(components, dict)
        assert 'component_a' in components
        assert 'component_b' in components
        assert components['component_a'].equals(comp_a)
        assert components['component_b'].equals(comp_b)

    def test_get_composite_signal(self):
        """get_composite_signal() should combine components using weights"""
        dates = pd.date_range('2020-01-01', periods=3)
        assets = ['ES', 'TY']

        comp_a = pd.DataFrame(
            [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
            index=dates,
            columns=assets
        )
        comp_b = pd.DataFrame(
            [[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]],
            index=dates,
            columns=assets
        )

        signal = MockDecomposableSignal(
            {'component_a': comp_a, 'component_b': comp_b},
            component_weights={'component_a': 0.3, 'component_b': 0.7}
        )

        composite = signal.get_composite_signal()

        # Expected: 0.3 * comp_a + 0.7 * comp_b
        expected = pd.DataFrame(
            [[7.3, 14.6], [21.9, 29.2], [36.5, 43.8]],
            index=dates,
            columns=assets
        )

        pd.testing.assert_frame_equal(composite, expected)

    def test_component_weights_attribute(self):
        """Should be able to set and get component_weights"""
        dates = pd.date_range('2020-01-01', periods=2)
        comp_a = pd.DataFrame([[1.0]], index=dates[:1], columns=['ES'])
        comp_b = pd.DataFrame([[2.0]], index=dates[:1], columns=['ES'])

        weights = {'component_a': 0.4, 'component_b': 0.6}
        signal = MockDecomposableSignal(
            {'component_a': comp_a, 'component_b': comp_b},
            component_weights=weights
        )

        assert signal.component_weights == weights

    def test_equal_weights(self):
        """Default weights should be equal (1/n for n components)"""
        dates = pd.date_range('2020-01-01', periods=2)

        comp_a = pd.DataFrame([[1.0]], index=dates[:1], columns=['ES'])
        comp_b = pd.DataFrame([[2.0]], index=dates[:1], columns=['ES'])
        comp_c = pd.DataFrame([[3.0]], index=dates[:1], columns=['ES'])

        signal = MockDecomposableSignal({
            'component_a': comp_a,
            'component_b': comp_b,
            'component_c': comp_c
        })

        composite = signal.get_composite_signal()

        # Expected: (1 + 2 + 3) / 3 = 2.0
        expected = pd.DataFrame([[2.0]], index=dates[:1], columns=['ES'])

        pd.testing.assert_frame_equal(composite, expected)

    def test_custom_weights(self):
        """Should support different weights per component"""
        dates = pd.date_range('2020-01-01', periods=2)

        comp_a = pd.DataFrame([[10.0]], index=dates[:1], columns=['ES'])
        comp_b = pd.DataFrame([[20.0]], index=dates[:1], columns=['ES'])
        comp_c = pd.DataFrame([[30.0]], index=dates[:1], columns=['ES'])

        signal = MockDecomposableSignal(
            {
                'component_a': comp_a,
                'component_b': comp_b,
                'component_c': comp_c
            },
            component_weights={
                'component_a': 0.1,
                'component_b': 0.2,
                'component_c': 0.7
            }
        )

        composite = signal.get_composite_signal()

        # Expected: 0.1*10 + 0.2*20 + 0.7*30 = 1 + 4 + 21 = 26.0
        expected = pd.DataFrame([[26.0]], index=dates[:1], columns=['ES'])

        pd.testing.assert_frame_equal(composite, expected)

    def test_zero_weight(self):
        """Component with zero weight should be excluded from composite"""
        dates = pd.date_range('2020-01-01', periods=2)

        comp_a = pd.DataFrame([[5.0]], index=dates[:1], columns=['ES'])
        comp_b = pd.DataFrame([[10.0]], index=dates[:1], columns=['ES'])

        signal = MockDecomposableSignal(
            {'component_a': comp_a, 'component_b': comp_b},
            component_weights={'component_a': 0.0, 'component_b': 1.0}
        )

        composite = signal.get_composite_signal()

        # Expected: 0.0*5 + 1.0*10 = 10.0
        expected = pd.DataFrame([[10.0]], index=dates[:1], columns=['ES'])

        pd.testing.assert_frame_equal(composite, expected)

    def test_single_component(self):
        """Should handle single component edge case"""
        dates = pd.date_range('2020-01-01', periods=2)

        comp_a = pd.DataFrame([[7.5]], index=dates[:1], columns=['ES'])

        signal = MockDecomposableSignal({'component_a': comp_a})

        composite = signal.get_composite_signal()

        # Expected: 1.0 * 7.5 = 7.5
        expected = pd.DataFrame([[7.5]], index=dates[:1], columns=['ES'])

        pd.testing.assert_frame_equal(composite, expected)

    def test_negative_weights(self):
        """Should allow negative weights for inverse positioning"""
        dates = pd.date_range('2020-01-01', periods=2)

        comp_a = pd.DataFrame([[10.0]], index=dates[:1], columns=['ES'])
        comp_b = pd.DataFrame([[5.0]], index=dates[:1], columns=['ES'])

        signal = MockDecomposableSignal(
            {'component_a': comp_a, 'component_b': comp_b},
            component_weights={'component_a': 1.0, 'component_b': -0.5}
        )

        composite = signal.get_composite_signal()

        # Expected: 1.0*10 + (-0.5)*5 = 10 - 2.5 = 7.5
        expected = pd.DataFrame([[7.5]], index=dates[:1], columns=['ES'])

        pd.testing.assert_frame_equal(composite, expected)

    def test_composite_signal_shape(self):
        """Composite signal should match component shape"""
        dates = pd.date_range('2020-01-01', periods=4)
        assets = ['ES', 'TY', 'GC']

        comp_a = pd.DataFrame(
            np.ones((4, 3)),
            index=dates,
            columns=assets
        )
        comp_b = pd.DataFrame(
            np.ones((4, 3)) * 2,
            index=dates,
            columns=assets
        )

        signal = MockDecomposableSignal(
            {'component_a': comp_a, 'component_b': comp_b},
            component_weights={'component_a': 0.5, 'component_b': 0.5}
        )

        composite = signal.get_composite_signal()

        assert composite.shape == (4, 3)
        assert list(composite.index) == list(dates)
        assert list(composite.columns) == assets
