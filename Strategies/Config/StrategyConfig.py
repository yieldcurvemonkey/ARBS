# ABOUTME: YAML configuration parser and validator for trading strategies
# ABOUTME: Loads strategy definitions from YAML files and validates against schema
"""
StrategyConfig - Configuration Parser for Trading Strategies

Parses YAML configuration files and validates them against the schema.
Provides a structured Python object for strategy creation.

Example:
    >>> config = StrategyConfig.from_yaml('strategy.yaml')
    >>> config.strategy.name
    'Simple Carry Strategy'
    >>> config.signals[0].type
    'carry'
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import date
import yaml
import json
from pathlib import Path


@dataclass
class SignalConfig:
    """Configuration for a single signal."""
    type: str
    config: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0

    def __post_init__(self):
        """Validate signal configuration."""
        # Import here to avoid circular dependencies
        from Strategies.Factory.SignalFactory import SignalFactory

        # Allow all registered signal types plus 'custom'
        valid_types = SignalFactory.list_available_signals() + ['custom']
        if self.type not in valid_types:
            raise ValueError(
                f"Invalid signal type '{self.type}'. "
                f"Available types: {valid_types}. "
                f"Use SignalFactory.register_signal() to add new types."
            )

        if self.weight < 0:
            raise ValueError(f"Signal weight must be non-negative, got {self.weight}")


@dataclass
class AlphaConfig:
    """Configuration for alpha generation."""
    IC: float = 0.05
    method: str = 'static'
    ic_lookback: int = 60
    ic_halflife: int = 30

    def __post_init__(self):
        """Validate alpha configuration."""
        if not 0 < self.IC < 1:
            raise ValueError(f"IC must be between 0 and 1, got {self.IC}")

        # Import here to avoid circular dependencies
        from Strategies.Factory.AlphaFactory import AlphaFactory

        valid_methods = AlphaFactory.list_available_methods()
        if self.method not in valid_methods:
            raise ValueError(
                f"Invalid IC method '{self.method}'. "
                f"Available methods: {valid_methods}. "
                f"Use AlphaFactory.register_method() to add new methods."
            )


@dataclass
class RiskConfig:
    """Configuration for risk model."""
    covariance: str = 'ledoit_wolf'
    volatility_target: Optional[float] = None
    lookback: int = 60

    def __post_init__(self):
        """Validate risk configuration."""
        # Import here to avoid circular dependencies
        from Strategies.Factory.CovarianceFactory import CovarianceFactory

        valid_covariance = CovarianceFactory.list_available_methods()
        if self.covariance not in valid_covariance:
            raise ValueError(
                f"Invalid covariance method '{self.covariance}'. "
                f"Available methods: {valid_covariance}. "
                f"Use CovarianceFactory.register_covariance() to add new methods."
            )

        if self.volatility_target is not None and self.volatility_target <= 0:
            raise ValueError(f"Volatility target must be positive, got {self.volatility_target}")


@dataclass
class OptimizerConstraints:
    """Optimizer constraints."""
    long_only: bool = True
    max_position: float = 0.30
    leverage: float = 1.0
    min_position: float = 0.0

    def __post_init__(self):
        """Validate constraints."""
        if not 0 < self.max_position <= 1:
            raise ValueError(f"max_position must be between 0 and 1, got {self.max_position}")

        if self.leverage < 0:
            raise ValueError(f"leverage must be non-negative, got {self.leverage}")


@dataclass
class OptimizerConfig:
    """Configuration for portfolio optimizer."""
    type: str = 'mean_variance'
    risk_aversion: float = 1.0
    constraints: OptimizerConstraints = field(default_factory=OptimizerConstraints)

    def __post_init__(self):
        """Validate optimizer configuration."""
        valid_types = ['mean_variance']
        if self.type not in valid_types:
            raise ValueError(f"Invalid optimizer type '{self.type}'. Must be one of {valid_types}")

        if self.risk_aversion <= 0:
            raise ValueError(f"risk_aversion must be positive, got {self.risk_aversion}")


@dataclass
class ExecutionConfig:
    """Configuration for execution."""
    rebalance_frequency: str = 'weekly'
    transaction_costs: float = 0.0

    def __post_init__(self):
        """Validate execution configuration."""
        valid_frequencies = ['daily', 'weekly', 'monthly', 'event_driven']
        if self.rebalance_frequency not in valid_frequencies:
            raise ValueError(f"Invalid rebalance_frequency '{self.rebalance_frequency}'. Must be one of {valid_frequencies}")

        if self.transaction_costs < 0:
            raise ValueError(f"transaction_costs must be non-negative, got {self.transaction_costs}")


@dataclass
class BacktestConfig:
    """Configuration for backtest."""
    start_date: str
    end_date: str
    initial_capital: float = 1_000_000.0

    def __post_init__(self):
        """Validate backtest configuration."""
        # Parse dates to ensure they're valid
        try:
            self.start_date_obj = date.fromisoformat(self.start_date)
            self.end_date_obj = date.fromisoformat(self.end_date)
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")

        if self.start_date_obj >= self.end_date_obj:
            raise ValueError(f"start_date must be before end_date")

        if self.initial_capital <= 0:
            raise ValueError(f"initial_capital must be positive, got {self.initial_capital}")


@dataclass
class UniverseConfig:
    """Configuration for instrument universe."""
    asset_class: str
    instruments: List[str]

    def __post_init__(self):
        """Validate universe configuration."""
        valid_asset_classes = ['futures', 'swaps', 'bonds']
        if self.asset_class not in valid_asset_classes:
            raise ValueError(f"Invalid asset_class '{self.asset_class}'. Must be one of {valid_asset_classes}")

        if not self.instruments:
            raise ValueError("instruments list cannot be empty")


@dataclass
class StrategyMetadata:
    """Strategy metadata."""
    name: str
    type: str
    description: str = ""

    def __post_init__(self):
        """Validate metadata."""
        valid_types = ['carry', 'momentum', 'mean_reversion', 'curve_trade', 'multi_signal', 'custom']
        if self.type not in valid_types:
            raise ValueError(f"Invalid strategy type '{self.type}'. Must be one of {valid_types}")


@dataclass
class StrategyConfig:
    """Complete strategy configuration."""
    strategy: StrategyMetadata
    universe: UniverseConfig
    signals: List[SignalConfig]
    alpha: AlphaConfig
    risk: RiskConfig
    optimizer: OptimizerConfig
    execution: ExecutionConfig
    backtest: BacktestConfig

    @classmethod
    def from_yaml(cls, yaml_path: str) -> 'StrategyConfig':
        """
        Load strategy configuration from YAML file.

        Args:
            yaml_path: Path to YAML configuration file

        Returns:
            StrategyConfig object

        Raises:
            FileNotFoundError: If YAML file doesn't exist
            ValueError: If configuration is invalid

        Example:
            >>> config = StrategyConfig.from_yaml('strategy.yaml')
            >>> print(config.strategy.name)
            'Simple Carry Strategy'
        """
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StrategyConfig':
        """
        Create configuration from dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            StrategyConfig object

        Example:
            >>> data = {'strategy': {'name': 'Test', 'type': 'carry'}, ...}
            >>> config = StrategyConfig.from_dict(data)
        """
        # Validate required top-level keys
        required_keys = ['strategy', 'universe', 'signals']
        for key in required_keys:
            if key not in data:
                raise ValueError(f"Missing required configuration key: '{key}'")

        # Parse strategy metadata (filter unknown fields)
        strategy_data = {k: v for k, v in data['strategy'].items() if k in ['name', 'type', 'description']}
        strategy = StrategyMetadata(**strategy_data)

        # Parse universe (filter unknown fields)
        universe_data = {k: v for k, v in data['universe'].items() if k in ['asset_class', 'instruments']}
        universe = UniverseConfig(**universe_data)

        # Parse signals (filter unknown fields)
        signals = []
        for sig_data in data['signals']:
            sig_filtered = {k: v for k, v in sig_data.items() if k in ['type', 'config', 'weight']}
            signals.append(SignalConfig(**sig_filtered))
        if not signals:
            raise ValueError("At least one signal is required")

        # Parse alpha (with defaults)
        alpha = AlphaConfig(**data.get('alpha', {}))

        # Parse risk (with defaults)
        risk = RiskConfig(**data.get('risk', {}))

        # Parse optimizer (with defaults)
        optimizer_data = data.get('optimizer', {})
        constraints_data = optimizer_data.pop('constraints', {})
        constraints = OptimizerConstraints(**constraints_data)
        optimizer = OptimizerConfig(constraints=constraints, **optimizer_data)

        # Parse execution (with defaults, filter unknown fields)
        execution_data = data.get('execution', {})
        execution_filtered = {k: v for k, v in execution_data.items() if k in ['rebalance_frequency', 'transaction_costs']}
        execution = ExecutionConfig(**execution_filtered)

        # Parse backtest (filter unknown fields)
        if 'backtest' not in data:
            raise ValueError("Missing required configuration key: 'backtest'")
        backtest_data = {k: v for k, v in data['backtest'].items() if k in ['start_date', 'end_date', 'initial_capital']}
        backtest = BacktestConfig(**backtest_data)

        return cls(
            strategy=strategy,
            universe=universe,
            signals=signals,
            alpha=alpha,
            risk=risk,
            optimizer=optimizer,
            execution=execution,
            backtest=backtest
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.

        Returns:
            Dictionary representation of configuration
        """
        return {
            'strategy': {
                'name': self.strategy.name,
                'type': self.strategy.type,
                'description': self.strategy.description
            },
            'universe': {
                'asset_class': self.universe.asset_class,
                'instruments': self.universe.instruments
            },
            'signals': [
                {
                    'type': sig.type,
                    'config': sig.config,
                    'weight': sig.weight
                }
                for sig in self.signals
            ],
            'alpha': {
                'IC': self.alpha.IC,
                'method': self.alpha.method,
                'ic_lookback': self.alpha.ic_lookback,
                'ic_halflife': self.alpha.ic_halflife
            },
            'risk': {
                'covariance': self.risk.covariance,
                'volatility_target': self.risk.volatility_target,
                'lookback': self.risk.lookback
            },
            'optimizer': {
                'type': self.optimizer.type,
                'risk_aversion': self.optimizer.risk_aversion,
                'constraints': {
                    'long_only': self.optimizer.constraints.long_only,
                    'max_position': self.optimizer.constraints.max_position,
                    'leverage': self.optimizer.constraints.leverage,
                    'min_position': self.optimizer.constraints.min_position
                }
            },
            'execution': {
                'rebalance_frequency': self.execution.rebalance_frequency,
                'transaction_costs': self.execution.transaction_costs
            },
            'backtest': {
                'start_date': self.backtest.start_date,
                'end_date': self.backtest.end_date,
                'initial_capital': self.backtest.initial_capital
            }
        }

    def validate(self) -> None:
        """
        Validate entire configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        # All validation happens in __post_init__ methods
        # This method is for additional cross-field validation

        # Validate signal count makes sense for strategy type
        if self.strategy.type in ['carry', 'momentum', 'mean_reversion'] and len(self.signals) > 1:
            # Single-signal strategy with multiple signals - warn or error?
            pass  # Allow for now

        # Validate IC method compatibility with signal count
        if self.alpha.method in ['rolling', 'ewma', 'regime'] and len(self.signals) == 1:
            # Dynamic IC with single signal requires historical returns
            pass  # Allow for now


def load_schema() -> Dict[str, Any]:
    """
    Load JSON schema for validation.

    Returns:
        JSON schema dictionary
    """
    schema_path = Path(__file__).parent / 'schema.json'
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    with open(schema_path, 'r') as f:
        return json.load(f)


def validate_against_schema(config_dict: Dict[str, Any]) -> None:
    """
    Validate configuration dictionary against JSON schema.

    Args:
        config_dict: Configuration dictionary

    Raises:
        ValueError: If configuration doesn't match schema
    """
    try:
        import jsonschema
        schema = load_schema()
        jsonschema.validate(config_dict, schema)
    except ImportError:
        # jsonschema not installed, skip schema validation
        pass
    except Exception as e:
        raise ValueError(f"Schema validation failed: {e}")
