# ABOUTME: Abstract base class for signals composed of multiple weighted components
# ABOUTME: Provides framework for combining signal components with configurable weights

from abc import ABC, abstractmethod
from typing import Dict
import pandas as pd


class DecomposableSignal(ABC):
    """
    Abstract base class for signals that can be decomposed into multiple components.

    A decomposable signal combines multiple signal components using weighted averaging.
    Each component is a DataFrame with the same shape (dates x assets), and the final
    composite signal is the weighted sum of all components.

    Subclasses must implement get_components() to define the signal components.
    """

    def __init__(self, component_weights: Dict[str, float] = None):
        """
        Initialize the decomposable signal.

        Args:
            component_weights: Optional dict mapping component names to weights.
                             If None, equal weights (1/n) will be used.
        """
        self._component_weights = component_weights

    @property
    def component_weights(self) -> Dict[str, float]:
        """Get component weights, using equal weights if not specified"""
        if self._component_weights is not None:
            return self._component_weights

        # Calculate equal weights based on number of components
        components = self.get_components()
        n_components = len(components)
        return {name: 1.0 / n_components for name in components.keys()}

    @abstractmethod
    def get_components(self) -> Dict[str, pd.DataFrame]:
        """
        Get the individual signal components.

        Returns:
            Dict mapping component name to DataFrame of signals.
            All DataFrames must have the same shape (dates x assets).

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclasses must implement get_components()")

    def get_composite_signal(self) -> pd.DataFrame:
        """
        Compute the composite signal as a weighted sum of components.

        Returns:
            DataFrame: Weighted combination of all components.
                      Shape matches component DataFrames (dates x assets).

        Formula:
            composite_signal = Σ (weight_i × component_i)
        """
        components = self.get_components()
        weights = self.component_weights

        # Initialize composite signal with zeros matching the shape of first component
        first_component = next(iter(components.values()))
        composite = pd.DataFrame(
            0.0,
            index=first_component.index,
            columns=first_component.columns
        )

        # Add weighted components
        for component_name, component_df in components.items():
            weight = weights.get(component_name, 0.0)
            composite += weight * component_df

        return composite
