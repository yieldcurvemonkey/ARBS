# ABOUTME: Factory for creating AlphaGenerator configurations from YAML
# ABOUTME: Registry-based pattern allowing runtime extension of IC methods
"""
AlphaFactory - Factory for AlphaGenerator Creation

Creates AlphaGenerator instances from StrategyConfig using registry pattern.
Allows runtime extension of IC methods without modifying this file.

Example:
    >>> # Built-in methods work out of box
    >>> config = StrategyConfig.from_dict({...})
    >>> alpha_gen = AlphaFactory.create_alpha_generator(config)

    >>> # Register custom IC method
    >>> def custom_ic_method(config):
    ...     return AlphaGenerator(IC=config.alpha.IC, custom_param=True)
    >>> AlphaFactory.register_method('custom_ic', custom_ic_method)
"""

from typing import Callable, Dict, List
from Signals.AlphaGenerator import AlphaGenerator


class AlphaFactory:
    """
    Factory for creating AlphaGenerator instances from configuration.

    Uses registry pattern to allow runtime registration of new IC methods
    without modifying this file.
    """

    # Registry of IC methods to creator functions
    _METHOD_REGISTRY: Dict[str, Callable] = {}

    @classmethod
    def _initialize_defaults(cls):
        """Initialize default IC methods."""
        if cls._METHOD_REGISTRY:
            return  # Already initialized

        cls._METHOD_REGISTRY = {
            'static': cls._create_static,
            'rolling': cls._create_rolling,
            'ewma': cls._create_ewma,
            'regime': cls._create_regime,
        }

    @classmethod
    def _create_static(cls, config) -> AlphaGenerator:
        """Create static IC alpha generator."""
        return AlphaGenerator(IC=config.alpha.IC)

    @classmethod
    def _create_rolling(cls, config) -> AlphaGenerator:
        """Create rolling IC alpha generator."""
        return AlphaGenerator(
            IC=config.alpha.IC,
            dynamic_ic=True,
            ic_method='rolling',
            ic_lookback=config.alpha.ic_lookback
        )

    @classmethod
    def _create_ewma(cls, config) -> AlphaGenerator:
        """Create EWMA IC alpha generator."""
        return AlphaGenerator(
            IC=config.alpha.IC,
            dynamic_ic=True,
            ic_method='ewma',
            ic_halflife=config.alpha.ic_halflife
        )

    @classmethod
    def _create_regime(cls, config) -> AlphaGenerator:
        """Create regime-based IC alpha generator."""
        return AlphaGenerator(
            IC=config.alpha.IC,
            dynamic_ic=True,
            ic_method='regime'
        )

    @classmethod
    def create_alpha_generator(cls, config) -> AlphaGenerator:
        """
        Create AlphaGenerator from configuration.

        Args:
            config: StrategyConfig instance

        Returns:
            AlphaGenerator instance

        Raises:
            ValueError: If IC method is unknown

        Example:
            >>> config = StrategyConfig.from_yaml('strategy.yaml')
            >>> alpha_gen = AlphaFactory.create_alpha_generator(config)
        """
        cls._initialize_defaults()

        method = config.alpha.method
        if method not in cls._METHOD_REGISTRY:
            available = ', '.join(cls.list_available_methods())
            raise ValueError(
                f"Unknown IC method: '{method}'. "
                f"Available methods: {available}"
            )

        creator_func = cls._METHOD_REGISTRY[method]
        return creator_func(config)

    @classmethod
    def register_method(
        cls,
        name: str,
        creator_func: Callable
    ) -> None:
        """
        Register a new IC method.

        Args:
            name: Method name (e.g., 'adaptive_ic')
            creator_func: Function that takes StrategyConfig and returns AlphaGenerator

        Example:
            >>> def create_adaptive_ic(config) -> AlphaGenerator:
            ...     return AlphaGenerator(IC=config.alpha.IC, adaptive=True)
            >>> AlphaFactory.register_method('adaptive', create_adaptive_ic)
        """
        cls._initialize_defaults()
        cls._METHOD_REGISTRY[name] = creator_func

    @classmethod
    def list_available_methods(cls) -> List[str]:
        """
        List all registered IC methods.

        Returns:
            List of method names

        Example:
            >>> AlphaFactory.list_available_methods()
            ['static', 'rolling', 'ewma', 'regime']
        """
        cls._initialize_defaults()
        return list(cls._METHOD_REGISTRY.keys())
