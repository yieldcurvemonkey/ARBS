# ABOUTME: Factory for creating risk models using registry pattern
# ABOUTME: Supports registration, creation by name, listing models, and dynamic extension without code modification
"""
RiskModelFactory - Registry Pattern for Risk Model Creation

Simple registry-based factory for creating risk models by name.
Allows runtime registration of new risk model classes without modifying this file.

Example:
    >>> # Create factory instance
    >>> factory = RiskModelFactory()

    >>> # Register models
    >>> factory.register('sample', SampleCovariance)
    >>> factory.register('ledoit_wolf', LedoitWolfShrinkage)

    >>> # Create models by name
    >>> model = factory.create('ledoit_wolf')

    >>> # Create with parameters
    >>> model = factory.create('ledoit_wolf', target='diagonal')

    >>> # List available models
    >>> models = factory.list_models()  # ['sample', 'ledoit_wolf']

Design:
- Instance-based (each factory has its own registry)
- No default models (explicit registration required)
- Simple API: register, create, list_models
- Support for kwargs to pass to model constructors
"""

from typing import Type, Dict, List


class RiskModelFactory:
    """
    Factory for creating risk models from registered classes.

    Uses registry pattern to allow runtime registration of risk models
    without modifying this file.
    """

    def __init__(self):
        """Initialize factory with empty registry."""
        self._registry: Dict[str, Type] = {}

    def register(self, name: str, model_class: Type) -> None:
        """
        Register a risk model class.

        Args:
            name: Model name (e.g., 'ledoit_wolf', 'sample')
            model_class: Risk model class to register

        Raises:
            TypeError: If model_class is None
            ValueError: If model_class is None

        Example:
            >>> factory.register('sample', SampleCovariance)
        """
        if model_class is None:
            raise TypeError("Cannot register None as a model class")

        self._registry[name] = model_class

    def create(self, name: str, **kwargs) -> object:
        """
        Create a risk model instance by name.

        Args:
            name: Registered model name
            **kwargs: Arguments to pass to model constructor

        Returns:
            Risk model instance

        Raises:
            KeyError: If model name is not registered

        Example:
            >>> model = factory.create('ledoit_wolf', target='diagonal')
        """
        if name not in self._registry:
            raise KeyError(
                f"Unknown risk model: '{name}'. "
                f"Available models: {', '.join(self.list_models())}"
            )

        model_class = self._registry[name]
        return model_class(**kwargs)

    def list_models(self) -> List[str]:
        """
        List all registered model names.

        Returns:
            List of registered model names

        Example:
            >>> factory.list_models()
            ['sample', 'ledoit_wolf']
        """
        return list(self._registry.keys())

    def get_model_class(self, name: str) -> Type:
        """
        Get model class without instantiation.

        Args:
            name: Registered model name

        Returns:
            Model class

        Raises:
            KeyError: If model name is not registered

        Example:
            >>> model_class = factory.get_model_class('ledoit_wolf')
            >>> model = model_class(target='diagonal')
        """
        if name not in self._registry:
            raise KeyError(
                f"Unknown risk model: '{name}'. "
                f"Available models: {', '.join(self.list_models())}"
            )

        return self._registry[name]

    def unregister(self, name: str) -> None:
        """
        Remove a model from the registry.

        Args:
            name: Model name to unregister

        Raises:
            KeyError: If model name is not registered

        Example:
            >>> factory.unregister('sample')
        """
        if name not in self._registry:
            raise KeyError(f"Model '{name}' is not registered")

        del self._registry[name]

    def clear(self) -> None:
        """
        Clear all registered models.

        Example:
            >>> factory.clear()
            >>> factory.list_models()
            []
        """
        self._registry.clear()

    def __repr__(self) -> str:
        """String representation."""
        models = ', '.join(self.list_models())
        return f"RiskModelFactory(models=[{models}])"
