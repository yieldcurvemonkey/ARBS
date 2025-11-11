# ABOUTME: Factory for creating covariance estimators from YAML configuration
# ABOUTME: Registry-based pattern for extensible risk model selection
"""
CovarianceFactory - Factory for Covariance Estimator Creation

Creates covariance estimator instances from StrategyConfig using registry pattern.
Allows runtime extension of covariance methods without modifying this file.

Example:
    >>> # Built-in estimators work out of box
    >>> config = StrategyConfig.from_dict({...})
    >>> cov_estimator = CovarianceFactory.create_covariance_estimator(config)

    >>> # Register custom estimator
    >>> from my_models import CustomCovariance
    >>> CovarianceFactory.register_covariance('custom', CustomCovariance)
"""

from typing import Type, Dict, List


class CovarianceFactory:
    """
    Factory for creating covariance estimators from configuration.

    Uses registry pattern to allow runtime registration of new covariance
    estimators without modifying this file.
    """

    # Registry of covariance methods to classes
    _COVARIANCE_REGISTRY: Dict[str, Type] = {}

    @classmethod
    def _initialize_defaults(cls):
        """Initialize default covariance estimators."""
        if cls._COVARIANCE_REGISTRY:
            return  # Already initialized

        # Import here to avoid circular dependencies
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        from Risk.Covariance.SampleCovariance import SampleCovariance

        cls._COVARIANCE_REGISTRY = {
            'ledoit_wolf': LedoitWolfShrinkage,
            'sample': SampleCovariance,
            'constant_correlation': LedoitWolfShrinkage,  # Same as ledoit_wolf for now
        }

    @classmethod
    def create_covariance_estimator(cls, config):
        """
        Create covariance estimator from configuration.

        Args:
            config: StrategyConfig instance

        Returns:
            Covariance estimator instance

        Raises:
            ValueError: If covariance method is unknown

        Example:
            >>> config = StrategyConfig.from_yaml('strategy.yaml')
            >>> cov = CovarianceFactory.create_covariance_estimator(config)
        """
        cls._initialize_defaults()

        method = config.risk.covariance
        if method not in cls._COVARIANCE_REGISTRY:
            available = ', '.join(cls.list_available_methods())
            raise ValueError(
                f"Unknown covariance method: '{method}'. "
                f"Available methods: {available}"
            )

        estimator_class = cls._COVARIANCE_REGISTRY[method]
        return estimator_class()

    @classmethod
    def register_covariance(cls, name: str, estimator_class: Type) -> None:
        """
        Register a new covariance estimator.

        Args:
            name: Method name (e.g., 'robust_covariance')
            estimator_class: Covariance estimator class

        Example:
            >>> from Risk.Covariance.RobustCovariance import RobustCovariance
            >>> CovarianceFactory.register_covariance('robust', RobustCovariance)
        """
        cls._initialize_defaults()
        cls._COVARIANCE_REGISTRY[name] = estimator_class

    @classmethod
    def list_available_methods(cls) -> List[str]:
        """
        List all registered covariance methods.

        Returns:
            List of method names

        Example:
            >>> CovarianceFactory.list_available_methods()
            ['ledoit_wolf', 'sample', 'constant_correlation']
        """
        cls._initialize_defaults()
        return list(cls._COVARIANCE_REGISTRY.keys())
