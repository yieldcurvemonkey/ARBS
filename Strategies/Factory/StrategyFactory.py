# ABOUTME: Main factory for creating GrinoldKahnPortfolio objects from YAML configuration
# ABOUTME: Orchestrates signal, alpha, risk, and optimizer instantiation into complete strategies
"""
StrategyFactory - Create Trading Strategies from YAML Configuration

Main factory that orchestrates the creation of complete GrinoldKahnPortfolio
objects from YAML configuration files.

Example:
    >>> factory = StrategyFactory()
    >>> strategy = factory.create_from_yaml('carry_strategy.yaml')
    >>> isinstance(strategy, GrinoldKahnPortfolio)
    True
"""

from typing import Dict, Any
from pathlib import Path

from Strategies.Config.StrategyConfig import StrategyConfig
from Strategies.Factory.SignalFactory import SignalFactory
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Risk.Covariance.SampleCovariance import SampleCovariance
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer
from Asset.GrinoldKahnPortfolio import GrinoldKahnPortfolio


class StrategyFactory:
    """
    Factory for creating complete trading strategies from configuration.

    Creates GrinoldKahnPortfolio objects with all components configured
    according to YAML specification.
    """

    def __init__(self):
        """Initialize strategy factory."""
        pass

    def create_from_yaml(self, yaml_path: str) -> GrinoldKahnPortfolio:
        """
        Create strategy from YAML configuration file.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            GrinoldKahnPortfolio instance

        Raises:
            FileNotFoundError: If YAML file doesn't exist
            ValueError: If configuration is invalid

        Example:
            >>> factory = StrategyFactory()
            >>> strategy = factory.create_from_yaml('strategy.yaml')
            >>> strategy.identifier
            'Simple Carry Strategy'
        """
        config = StrategyConfig.from_yaml(yaml_path)
        return self.create_from_config(config)

    def create_from_dict(self, config_dict: Dict[str, Any]) -> GrinoldKahnPortfolio:
        """
        Create strategy from configuration dictionary.

        Args:
            config_dict: Configuration dictionary

        Returns:
            GrinoldKahnPortfolio instance

        Example:
            >>> config = {
            ...     'strategy': {'name': 'Test', 'type': 'carry'},
            ...     'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
            ...     'signals': [{'type': 'carry'}],
            ...     'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
            ... }
            >>> factory = StrategyFactory()
            >>> strategy = factory.create_from_dict(config)
        """
        config = StrategyConfig.from_dict(config_dict)
        return self.create_from_config(config)

    def create_from_config(self, config: StrategyConfig) -> GrinoldKahnPortfolio:
        """
        Create strategy from StrategyConfig object.

        Args:
            config: StrategyConfig instance

        Returns:
            GrinoldKahnPortfolio instance

        Example:
            >>> config = StrategyConfig.from_yaml('strategy.yaml')
            >>> factory = StrategyFactory()
            >>> strategy = factory.create_from_config(config)
        """
        # Create signals
        signals = SignalFactory.create_signals(config.signals)

        # Create alpha generator
        alpha_generator = self._create_alpha_generator(config)

        # Create risk model
        risk_model = self._create_risk_model(config)

        # Create optimizer
        optimizer = self._create_optimizer(config)

        # Create portfolio
        portfolio = GrinoldKahnPortfolio(
            identifier=config.strategy.name,
            signals=signals,
            alpha_generator=alpha_generator,
            risk_model=risk_model,
            optimizer=optimizer,
            rebalance_frequency=config.execution.rebalance_frequency
        )

        return portfolio

    def _create_alpha_generator(self, config: StrategyConfig) -> AlphaGenerator:
        """
        Create AlphaGenerator from configuration.

        Args:
            config: StrategyConfig instance

        Returns:
            AlphaGenerator instance
        """
        # Determine if dynamic IC is needed
        if config.alpha.method == 'static':
            alpha_gen = AlphaGenerator(IC=config.alpha.IC)
        elif config.alpha.method == 'rolling':
            alpha_gen = AlphaGenerator(
                IC=config.alpha.IC,
                dynamic_ic=True,
                ic_method='rolling',
                ic_lookback=config.alpha.ic_lookback
            )
        elif config.alpha.method == 'ewma':
            alpha_gen = AlphaGenerator(
                IC=config.alpha.IC,
                dynamic_ic=True,
                ic_method='ewma',
                ic_halflife=config.alpha.ic_halflife
            )
        elif config.alpha.method == 'regime':
            alpha_gen = AlphaGenerator(
                IC=config.alpha.IC,
                dynamic_ic=True,
                ic_method='regime'
            )
        else:
            raise ValueError(f"Unknown IC method: {config.alpha.method}")

        return alpha_gen

    def _create_risk_model(self, config: StrategyConfig):
        """
        Create covariance estimator from configuration.

        Args:
            config: StrategyConfig instance

        Returns:
            Covariance estimator instance
        """
        if config.risk.covariance == 'ledoit_wolf':
            return LedoitWolfShrinkage()
        elif config.risk.covariance == 'sample':
            return SampleCovariance()
        elif config.risk.covariance == 'constant_correlation':
            # Use Ledoit-Wolf with constant correlation target
            return LedoitWolfShrinkage()
        else:
            raise ValueError(f"Unknown covariance method: {config.risk.covariance}")

    def _create_optimizer(self, config: StrategyConfig) -> MeanVarianceOptimizer:
        """
        Create optimizer from configuration.

        Args:
            config: StrategyConfig instance

        Returns:
            MeanVarianceOptimizer instance
        """
        optimizer = MeanVarianceOptimizer(
            risk_aversion=config.optimizer.risk_aversion,
            long_only=config.optimizer.constraints.long_only,
            position_limit=config.optimizer.constraints.max_position,
            leverage_limit=config.optimizer.constraints.leverage if config.optimizer.constraints.leverage > 1.0 else None
        )

        return optimizer


def create_strategy(yaml_path: str) -> GrinoldKahnPortfolio:
    """
    Convenience function to create strategy from YAML file.

    Args:
        yaml_path: Path to YAML configuration file

    Returns:
        GrinoldKahnPortfolio instance

    Example:
        >>> from Strategies.Factory import create_strategy
        >>> strategy = create_strategy('carry_strategy.yaml')
        >>> strategy.identifier
        'Simple Carry Strategy'
    """
    factory = StrategyFactory()
    return factory.create_from_yaml(yaml_path)
