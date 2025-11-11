# ABOUTME: Factory for instantiating signal objects from YAML configuration
# ABOUTME: Maps signal type strings to signal classes and applies configuration parameters
"""
SignalFactory - Create Signal Objects from Configuration

Instantiates signal objects (Carry, Momentum, Mean Reversion) from
configuration dictionaries.

Example:
    >>> config = {'type': 'carry', 'config': {'standardize': True}}
    >>> signal = SignalFactory.create_signal(config)
    >>> isinstance(signal, CarrySignal)
    True
"""

from typing import Dict, Any, List
from Signals.Base.BaseSignal import BaseSignal
from Signals.Futures.CarrySignal import CarrySignal
from Signals.Futures.MomentumSignal import MomentumSignal
from Signals.Futures.MeanReversionSignal import MeanReversionSignal
from Strategies.Config.StrategyConfig import SignalConfig


class SignalFactory:
    """
    Factory for creating signal objects from configuration.

    Supports built-in signals (carry, momentum, mean_reversion) and
    custom signals via plugin system.
    """

    # Registry of signal types to classes
    _SIGNAL_REGISTRY = {
        'carry': CarrySignal,
        'momentum': MomentumSignal,
        'mean_reversion': MeanReversionSignal,
    }

    @classmethod
    def create_signal(cls, config: SignalConfig) -> BaseSignal:
        """
        Create a signal object from configuration.

        Args:
            config: SignalConfig object

        Returns:
            BaseSignal instance

        Raises:
            ValueError: If signal type is unknown

        Example:
            >>> config = SignalConfig(type='carry', config={'standardize': True})
            >>> signal = SignalFactory.create_signal(config)
            >>> signal.name
            'futures_carry'
        """
        signal_type = config.type

        if signal_type == 'custom':
            return cls._create_custom_signal(config)

        if signal_type not in cls._SIGNAL_REGISTRY:
            raise ValueError(f"Unknown signal type: '{signal_type}'. Available: {list(cls._SIGNAL_REGISTRY.keys())}")

        signal_class = cls._SIGNAL_REGISTRY[signal_type]

        # Extract configuration parameters
        params = config.config.copy()

        # Create signal instance
        try:
            signal = signal_class(**params)
        except TypeError as e:
            raise ValueError(f"Invalid configuration for {signal_type} signal: {e}")

        return signal

    @classmethod
    def create_signals(cls, configs: List[SignalConfig]) -> List[BaseSignal]:
        """
        Create multiple signals from configurations.

        Args:
            configs: List of SignalConfig objects

        Returns:
            List of BaseSignal instances

        Example:
            >>> configs = [
            ...     SignalConfig(type='carry'),
            ...     SignalConfig(type='momentum', config={'lookback_days': 30})
            ... ]
            >>> signals = SignalFactory.create_signals(configs)
            >>> len(signals)
            2
        """
        return [cls.create_signal(config) for config in configs]

    @classmethod
    def _create_custom_signal(cls, config: SignalConfig) -> BaseSignal:
        """
        Create a custom signal from plugin.

        Args:
            config: SignalConfig with type='custom'

        Returns:
            BaseSignal instance

        Raises:
            ValueError: If custom signal configuration is invalid

        Example:
            >>> config = SignalConfig(
            ...     type='custom',
            ...     config={
            ...         'module': 'my_signals.MySignal',
            ...         'class': 'MySignal',
            ...         'params': {'foo': 'bar'}
            ...     }
            ... )
            >>> signal = SignalFactory._create_custom_signal(config)
        """
        # Custom signal must specify module and class
        if 'module' not in config.config or 'class' not in config.config:
            raise ValueError("Custom signal must specify 'module' and 'class' in config")

        module_name = config.config['module']
        class_name = config.config['class']
        params = config.config.get('params', {})

        # Import the custom signal class
        try:
            import importlib
            module = importlib.import_module(module_name)
            signal_class = getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            raise ValueError(f"Failed to import custom signal {module_name}.{class_name}: {e}")

        # Verify it's a BaseSignal subclass
        if not issubclass(signal_class, BaseSignal):
            raise ValueError(f"Custom signal {class_name} must inherit from BaseSignal")

        # Instantiate
        try:
            signal = signal_class(**params)
        except TypeError as e:
            raise ValueError(f"Invalid parameters for custom signal {class_name}: {e}")

        return signal

    @classmethod
    def register_signal(cls, name: str, signal_class: type) -> None:
        """
        Register a new signal type.

        Args:
            name: Signal type name (e.g., 'my_signal')
            signal_class: Signal class (must inherit from BaseSignal)

        Raises:
            ValueError: If signal_class doesn't inherit from BaseSignal

        Example:
            >>> from Signals.Base.BaseSignal import BaseSignal
            >>> class MySignal(BaseSignal):
            ...     pass
            >>> SignalFactory.register_signal('my_signal', MySignal)
        """
        if not issubclass(signal_class, BaseSignal):
            raise ValueError(f"Signal class must inherit from BaseSignal, got {signal_class}")

        cls._SIGNAL_REGISTRY[name] = signal_class

    @classmethod
    def list_available_signals(cls) -> List[str]:
        """
        List all registered signal types.

        Returns:
            List of signal type names

        Example:
            >>> SignalFactory.list_available_signals()
            ['carry', 'momentum', 'mean_reversion']
        """
        return list(cls._SIGNAL_REGISTRY.keys())


def get_signal_defaults(signal_type: str) -> Dict[str, Any]:
    """
    Get default configuration parameters for a signal type.

    Args:
        signal_type: Signal type name

    Returns:
        Dictionary of default parameters

    Example:
        >>> get_signal_defaults('momentum')
        {'lookback_days': 60, 'method': 'simple', 'standardize': True}
    """
    defaults = {
        'carry': {
            'standardize': True,
            'annualize': True,
            'method': 'front_back'
        },
        'momentum': {
            'lookback_days': 60,
            'method': 'simple',
            'standardize': True,
            'annualize': False
        },
        'mean_reversion': {
            'lookback_days': 20,
            'method': 'zscore',
            'standardize': True
        }
    }

    return defaults.get(signal_type, {})
