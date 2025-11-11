# ABOUTME: Abstract base class for signal components in decomposable signal architecture
# ABOUTME: Defines the interface for individual components that can be combined into composite signals
from abc import ABC, abstractmethod
from typing import Any, Dict
import polars as pl


class SignalComponent(ABC):
    """
    Abstract base class for signal components.

    Signal components are the building blocks of decomposable signals.
    Each component implements a specific calculation that produces a DataFrame
    of signal values.

    Attributes:
        name (str): Component name for identification
        metadata (Dict[str, Any]): Additional component metadata
    """

    def __init__(self, name: str, metadata: Dict[str, Any] = None):
        """
        Initialize signal component.

        Args:
            name: Component name (e.g., "carry", "momentum", "value")
            metadata: Optional metadata dictionary for storing component information
        """
        self.name = name
        self.metadata = metadata if metadata is not None else {}

    @abstractmethod
    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Calculate component signal values.

        This method must be implemented by subclasses to define
        the specific calculation logic for the component.

        Args:
            data: Input data for signal calculation

        Returns:
            DataFrame of calculated signal values
        """
        pass
