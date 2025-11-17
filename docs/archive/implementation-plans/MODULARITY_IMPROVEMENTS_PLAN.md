# Modularity Improvements: Detailed Implementation Plan
**Date**: 2025-11-11
**Status**: Ready to Execute
**Goal**: Achieve 95% modularity (from current 75%)

## Executive Summary

**Current Blockers**:
- 5 hardcoded type lists prevent extension without code modification
- If/elif chains in StrategyFactory violate Open/Closed Principle
- No factory pattern for risk models

**Solution**: 3-phase implementation (9-13 hours)
- Phase 1: Component factories (4-6 hours)
- Phase 2: Dynamic validation (2-3 hours)
- Phase 3: Documentation (3-4 hours)

**Success Criteria**:
- ✅ Can add new signals without modifying StrategyConfig
- ✅ Can add new alpha methods without modifying StrategyFactory
- ✅ Can add new covariance estimators without modifying StrategyFactory
- ✅ All 559 existing tests pass
- ✅ 15+ new tests for factory patterns

---

## Phase 1: Component Factories

### Step 1.1: Create AlphaFactory

**Goal**: Replace if/elif chain in StrategyFactory._create_alpha_generator()

**File to Create**: `Strategies/Factory/AlphaFactory.py`

**Implementation**:
```python
# ABOUTME: Factory for creating AlphaGenerator configurations from YAML
# ABOUTME: Registry-based pattern allowing runtime extension of IC methods

from typing import Callable, Dict, List
from Signals.AlphaGenerator import AlphaGenerator
from Strategies.Config.StrategyConfig import StrategyConfig


class AlphaFactory:
    """
    Factory for creating AlphaGenerator instances from configuration.

    Uses registry pattern to allow runtime registration of new IC methods
    without modifying this file.

    Example:
        >>> # Built-in methods work out of box
        >>> config = StrategyConfig.from_dict({...})
        >>> alpha_gen = AlphaFactory.create_alpha_generator(config)

        >>> # Register custom IC method
        >>> def custom_ic_method(config):
        ...     return AlphaGenerator(IC=config.alpha.IC, custom_param=True)
        >>> AlphaFactory.register_method('custom_ic', custom_ic_method)
    """

    # Registry of IC methods to creator functions
    _METHOD_REGISTRY: Dict[str, Callable[[StrategyConfig], AlphaGenerator]] = {}

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
    def _create_static(cls, config: StrategyConfig) -> AlphaGenerator:
        """Create static IC alpha generator."""
        return AlphaGenerator(IC=config.alpha.IC)

    @classmethod
    def _create_rolling(cls, config: StrategyConfig) -> AlphaGenerator:
        """Create rolling IC alpha generator."""
        return AlphaGenerator(
            IC=config.alpha.IC,
            dynamic_ic=True,
            ic_method='rolling',
            ic_lookback=config.alpha.ic_lookback
        )

    @classmethod
    def _create_ewma(cls, config: StrategyConfig) -> AlphaGenerator:
        """Create EWMA IC alpha generator."""
        return AlphaGenerator(
            IC=config.alpha.IC,
            dynamic_ic=True,
            ic_method='ewma',
            ic_halflife=config.alpha.ic_halflife
        )

    @classmethod
    def _create_regime(cls, config: StrategyConfig) -> AlphaGenerator:
        """Create regime-based IC alpha generator."""
        return AlphaGenerator(
            IC=config.alpha.IC,
            dynamic_ic=True,
            ic_method='regime'
        )

    @classmethod
    def create_alpha_generator(cls, config: StrategyConfig) -> AlphaGenerator:
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
        creator_func: Callable[[StrategyConfig], AlphaGenerator]
    ) -> None:
        """
        Register a new IC method.

        Args:
            name: Method name (e.g., 'adaptive_ic')
            creator_func: Function that takes StrategyConfig and returns AlphaGenerator

        Example:
            >>> def create_adaptive_ic(config: StrategyConfig) -> AlphaGenerator:
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
```

**Tests to Create**: `tests/unit/strategies/test_alpha_factory.py`
```python
import pytest
from Strategies.Factory.AlphaFactory import AlphaFactory
from Strategies.Config.StrategyConfig import StrategyConfig
from Signals.AlphaGenerator import AlphaGenerator


def test_alpha_factory_static():
    """Test static IC method."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'static'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    alpha_gen = AlphaFactory.create_alpha_generator(config)

    assert isinstance(alpha_gen, AlphaGenerator)
    assert alpha_gen.IC == 0.05
    assert not alpha_gen.dynamic_ic


def test_alpha_factory_rolling():
    """Test rolling IC method."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'rolling', 'ic_lookback': 90},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    alpha_gen = AlphaFactory.create_alpha_generator(config)

    assert alpha_gen.dynamic_ic
    assert alpha_gen.ic_method == 'rolling'
    assert alpha_gen.ic_lookback == 90


def test_alpha_factory_custom_method():
    """Test registering custom IC method."""
    def custom_creator(config: StrategyConfig) -> AlphaGenerator:
        return AlphaGenerator(IC=config.alpha.IC * 2)

    AlphaFactory.register_method('double_ic', custom_creator)

    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'double_ic'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)
    alpha_gen = AlphaFactory.create_alpha_generator(config)

    assert alpha_gen.IC == 0.10


def test_alpha_factory_unknown_method():
    """Test error on unknown IC method."""
    config_dict = {
        'strategy': {'name': 'Test', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'nonexistent'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }
    config = StrategyConfig.from_dict(config_dict)

    with pytest.raises(ValueError, match="Unknown IC method"):
        AlphaFactory.create_alpha_generator(config)


def test_alpha_factory_list_methods():
    """Test listing available methods."""
    methods = AlphaFactory.list_available_methods()
    assert 'static' in methods
    assert 'rolling' in methods
    assert 'ewma' in methods
    assert 'regime' in methods
```

**Acceptance Criteria**:
- ✅ AlphaFactory.create_alpha_generator() works for all 4 built-in methods
- ✅ AlphaFactory.register_method() allows runtime extension
- ✅ AlphaFactory.list_available_methods() returns current registry
- ✅ Unknown methods raise ValueError with helpful message
- ✅ All tests pass (5+)

---

### Step 1.2: Create CovarianceFactory

**Goal**: Replace if/elif chain in StrategyFactory._create_risk_model()

**File to Create**: `Strategies/Factory/CovarianceFactory.py`

**Implementation**:
```python
# ABOUTME: Factory for creating covariance estimators from YAML configuration
# ABOUTME: Registry-based pattern for extensible risk model selection

from typing import Type, Dict, List
from Strategies.Config.StrategyConfig import StrategyConfig


class CovarianceFactory:
    """
    Factory for creating covariance estimators from configuration.

    Uses registry pattern to allow runtime registration of new covariance
    estimators without modifying this file.

    Example:
        >>> # Built-in estimators work out of box
        >>> config = StrategyConfig.from_dict({...})
        >>> cov_estimator = CovarianceFactory.create_covariance_estimator(config)

        >>> # Register custom estimator
        >>> from my_models import CustomCovariance
        >>> CovarianceFactory.register_covariance('custom', CustomCovariance)
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
            'constant_correlation': LedoitWolfShrinkage,  # Same as ledoit_wolf
        }

    @classmethod
    def create_covariance_estimator(cls, config: StrategyConfig):
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
```

**Tests to Create**: `tests/unit/strategies/test_covariance_factory.py`

**Acceptance Criteria**:
- ✅ CovarianceFactory.create_covariance_estimator() works for all 3 built-in methods
- ✅ CovarianceFactory.register_covariance() allows runtime extension
- ✅ CovarianceFactory.list_available_methods() returns current registry
- ✅ Unknown methods raise ValueError with helpful message
- ✅ All tests pass (5+)

---

### Step 1.3: Update StrategyFactory to Use New Factories

**Goal**: Replace if/elif chains with factory calls

**File to Modify**: `Strategies/Factory/StrategyFactory.py`

**Changes**:
```python
# Add imports at top
from Strategies.Factory.AlphaFactory import AlphaFactory
from Strategies.Factory.CovarianceFactory import CovarianceFactory

# Replace _create_alpha_generator (lines 125-161)
def _create_alpha_generator(self, config: StrategyConfig) -> AlphaGenerator:
    """
    Create AlphaGenerator from configuration.

    Args:
        config: StrategyConfig instance

    Returns:
        AlphaGenerator instance
    """
    return AlphaFactory.create_alpha_generator(config)

# Replace _create_risk_model (lines 163-181)
def _create_risk_model(self, config: StrategyConfig):
    """
    Create covariance estimator from configuration.

    Args:
        config: StrategyConfig instance

    Returns:
        Covariance estimator instance
    """
    return CovarianceFactory.create_covariance_estimator(config)
```

**Acceptance Criteria**:
- ✅ All existing 559 tests pass
- ✅ StrategyFactory code reduced by ~40 lines
- ✅ No if/elif chains remain in StrategyFactory
- ✅ Behavior identical to before (existing tests prove this)

---

### Step 1.4: Update StrategyConfig Validation to Query Registries

**Goal**: Replace hardcoded type lists with registry queries

**File to Modify**: `Strategies/Config/StrategyConfig.py`

**Changes**:

1. **SignalConfig.__post_init__ (Line 32-39)**
```python
def __post_init__(self):
    """Validate signal configuration."""
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
```

2. **AlphaConfig.__post_init__ (Line 50-57)**
```python
def __post_init__(self):
    """Validate alpha configuration."""
    if not 0 < self.IC < 1:
        raise ValueError(f"IC must be between 0 and 1, got {self.IC}")

    from Strategies.Factory.AlphaFactory import AlphaFactory

    valid_methods = AlphaFactory.list_available_methods()
    if self.method not in valid_methods:
        raise ValueError(
            f"Invalid IC method '{self.method}'. "
            f"Available methods: {valid_methods}. "
            f"Use AlphaFactory.register_method() to add new methods."
        )
```

3. **RiskConfig.__post_init__ (Line 67-74)**
```python
def __post_init__(self):
    """Validate risk configuration."""
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
```

**Acceptance Criteria**:
- ✅ All existing 559 tests pass
- ✅ Validation queries registries, not hardcoded lists
- ✅ Error messages include instructions for adding new types
- ✅ Can add new signal types without modifying StrategyConfig

---

### Step 1.5: Update Factory __init__.py Exports

**File to Modify**: `Strategies/Factory/__init__.py`

**Changes**:
```python
"""Factory module for instantiating strategies from configuration."""

from .SignalFactory import SignalFactory, get_signal_defaults
from .StrategyFactory import StrategyFactory, create_strategy
from .AlphaFactory import AlphaFactory
from .CovarianceFactory import CovarianceFactory

__all__ = [
    'SignalFactory',
    'StrategyFactory',
    'create_strategy',
    'get_signal_defaults',
    'AlphaFactory',
    'CovarianceFactory'
]
```

**Acceptance Criteria**:
- ✅ All factories importable from Strategies.Factory
- ✅ All existing imports still work

---

## Phase 2: Enhanced Validation & Usability

### Step 2.1: Add Validation Helper Messages

**Goal**: Provide better error messages with suggestions

**File to Modify**: `Strategies/Config/StrategyConfig.py`

**Add Helper Function**:
```python
def _suggest_similar_types(invalid_type: str, valid_types: List[str]) -> str:
    """
    Suggest similar valid types for typos.

    Args:
        invalid_type: The invalid type user provided
        valid_types: List of valid types

    Returns:
        Suggestion string or empty string
    """
    # Simple Levenshtein distance for suggestions
    import difflib
    close_matches = difflib.get_close_matches(invalid_type, valid_types, n=3, cutoff=0.6)

    if close_matches:
        return f" Did you mean: {', '.join(close_matches)}?"
    return ""
```

**Update Error Messages**:
```python
# In SignalConfig.__post_init__
if self.type not in valid_types:
    suggestion = _suggest_similar_types(self.type, valid_types)
    raise ValueError(
        f"Invalid signal type '{self.type}'. "
        f"Available types: {valid_types}.{suggestion}"
    )
```

**Acceptance Criteria**:
- ✅ Typos get helpful suggestions (e.g., 'momentun' → 'momentum')
- ✅ All existing tests pass
- ✅ Error messages more user-friendly

---

### Step 2.2: Add Integration Tests for Extension

**Goal**: Verify extension points work end-to-end

**File to Create**: `tests/integration/test_factory_extension.py`

**Tests**:
```python
import pytest
from Strategies.Factory import SignalFactory, AlphaFactory, CovarianceFactory
from Strategies.Config.StrategyConfig import StrategyConfig
from Strategies.Registry import quick_strategy
from Signals.Base.BaseSignal import BaseSignal
from Signals.AlphaGenerator import AlphaGenerator
import numpy as np


class CustomTestSignal(BaseSignal):
    """Custom signal for testing extension."""
    def __init__(self, multiplier: float = 1.0):
        super().__init__(name='custom_test_signal')
        self.multiplier = multiplier

    def calculate(self, prices, dates):
        # Simple test signal
        n = len(prices.columns)
        return pd.DataFrame(
            np.random.randn(len(dates), n) * self.multiplier,
            index=dates,
            columns=prices.columns
        )


def test_end_to_end_custom_signal():
    """Test adding custom signal and using in strategy."""
    # Register custom signal
    SignalFactory.register_signal('custom_test', CustomTestSignal)

    # Create config with custom signal
    config_dict = {
        'strategy': {'name': 'Custom Test', 'type': 'custom'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4', 'SFRH5']},
        'signals': [{'type': 'custom_test', 'config': {'multiplier': 2.0}}],
        'alpha': {'IC': 0.05, 'method': 'static'},
        'risk': {'covariance': 'ledoit_wolf'},
        'optimizer': {'type': 'mean_variance', 'risk_aversion': 1.0},
        'execution': {'rebalance_frequency': 'weekly'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }

    # Should not raise validation error
    config = StrategyConfig.from_dict(config_dict)
    assert len(config.signals) == 1
    assert config.signals[0].type == 'custom_test'


def test_end_to_end_custom_alpha_method():
    """Test adding custom alpha method and using in strategy."""
    # Register custom alpha method
    def custom_alpha_creator(config: StrategyConfig) -> AlphaGenerator:
        return AlphaGenerator(IC=config.alpha.IC * 1.5)

    AlphaFactory.register_method('custom_alpha', custom_alpha_creator)

    # Create config with custom alpha method
    config_dict = {
        'strategy': {'name': 'Custom Alpha', 'type': 'carry'},
        'universe': {'asset_class': 'futures', 'instruments': ['SFRZ4']},
        'signals': [{'type': 'carry'}],
        'alpha': {'IC': 0.05, 'method': 'custom_alpha'},
        'backtest': {'start_date': '2024-01-01', 'end_date': '2024-12-31'}
    }

    # Should not raise validation error
    config = StrategyConfig.from_dict(config_dict)
    assert config.alpha.method == 'custom_alpha'
```

**Acceptance Criteria**:
- ✅ End-to-end test passes for custom signal
- ✅ End-to-end test passes for custom alpha method
- ✅ End-to-end test passes for custom covariance estimator
- ✅ Demonstrates extension workflow

---

## Phase 3: Documentation

### Step 3.1: Create Extension Guide

**File to Create**: `docs/ADDING_CUSTOM_COMPONENTS.md`

**Content**: Comprehensive guide with:
- How to add custom signals
- How to add custom alpha methods
- How to add custom covariance estimators
- Complete working examples
- Troubleshooting section

**Acceptance Criteria**:
- ✅ Clear instructions for each extension point
- ✅ Working code examples
- ✅ Common pitfalls documented

---

### Step 3.2: Create Extension Examples

**File to Create**: `examples/custom_components_example.py`

**Content**: Runnable examples demonstrating:
- Custom signal registration
- Custom alpha method registration
- Custom covariance estimator registration
- YAML configuration for custom components
- End-to-end backtest with custom components

**Acceptance Criteria**:
- ✅ Example runs without errors
- ✅ Demonstrates all extension points
- ✅ Includes comments explaining each step

---

### Step 3.3: Update Main Documentation

**Files to Update**:
- `README.md`: Add section on extensibility
- `docs/ARCHITECTURE.md`: Document factory patterns
- `docs/USER_GUIDE.md`: Add custom components section

**Acceptance Criteria**:
- ✅ Extensibility prominently documented
- ✅ Links to detailed guides
- ✅ Architecture diagrams updated

---

## Verification Checklist

### After Each Step:
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Verify test count increases (559 → 574+)
- [ ] Check for any test failures
- [ ] Run example scripts to verify no breakage
- [ ] Git commit with descriptive message

### After Phase 1:
- [ ] All 559 existing tests pass
- [ ] 15+ new factory tests pass
- [ ] No if/elif chains in StrategyFactory
- [ ] Validation queries registries
- [ ] Can register custom signal and use in config

### After Phase 2:
- [ ] Error messages include suggestions
- [ ] Integration tests pass
- [ ] Extension workflow documented

### After Phase 3:
- [ ] Documentation complete
- [ ] Examples runnable
- [ ] User can follow guide to add custom component

---

## Success Metrics

**Before**:
- Modularity: 75%
- Hardcoded lists: 5
- If/elif chains: 2
- Lines in StrategyFactory: 221
- Extension requires: Code modification

**After**:
- Modularity: 95%
- Hardcoded lists: 0
- If/elif chains: 0
- Lines in StrategyFactory: ~180 (-40)
- Extension requires: Registration call only

**Test Coverage**:
- Before: 559 tests
- After: 574+ tests (+15 minimum)

---

## Risk Assessment

### Low Risk:
- ✅ All changes are refactoring (no behavior change)
- ✅ Existing tests prove correctness
- ✅ Factory pattern is well-established
- ✅ Can rollback if issues arise

### Mitigation:
- Run full test suite after each step
- Git commit after each successful step
- Keep existing code until new code proven

---

## Timeline Estimate

**Optimistic**: 9 hours (1 day)
**Realistic**: 11 hours (1.5 days)
**Pessimistic**: 13 hours (2 days)

**Breakdown**:
- Phase 1.1 (AlphaFactory): 1.5-2h
- Phase 1.2 (CovarianceFactory): 1-1.5h
- Phase 1.3 (Update StrategyFactory): 0.5h
- Phase 1.4 (Update validation): 1-1.5h
- Phase 1.5 (Update exports): 0.25h
- Phase 2.1 (Better errors): 0.5-1h
- Phase 2.2 (Integration tests): 1-1.5h
- Phase 3.1 (Extension guide): 1.5-2h
- Phase 3.2 (Examples): 1-1.5h
- Phase 3.3 (Update docs): 0.5-1h
- Testing & debugging: 1-2h

---

## Next Actions

1. ✅ Create this plan document
2. ⏭️ Create AlphaFactory.py
3. ⏭️ Create test_alpha_factory.py
4. ⏭️ Run tests, verify passes
5. ⏭️ Create CovarianceFactory.py
6. ⏭️ Continue through all steps...

---

**Last Updated**: 2025-11-11
**Status**: Ready to Execute
