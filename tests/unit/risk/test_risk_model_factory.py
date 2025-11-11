# ABOUTME: Tests for RiskModelFactory registry pattern for creating risk models by name
# ABOUTME: Validates registration, creation, listing, and error handling for risk model factory
"""
Tests for RiskModelFactory - registry-based risk model creation.

Tests cover:
- Model registration
- Model creation by name
- Listing available models
- Error handling for unknown models
- Kwargs passing to model constructors
- Multiple registrations
- Registry management
"""

import pytest
from Risk.risk_model_factory import RiskModelFactory


# Mock risk models for testing
class MockRiskModel:
    """Simple mock risk model for testing."""

    def __init__(self, param1='default', param2=None):
        self.param1 = param1
        self.param2 = param2
        self.model_type = 'mock'


class AnotherMockRiskModel:
    """Another mock risk model for testing."""

    def __init__(self, custom_param=100):
        self.custom_param = custom_param
        self.model_type = 'another_mock'


class TestRiskModelFactoryBasics:
    """Test basic RiskModelFactory functionality."""

    def test_register_model(self):
        """Test registering a mock model."""
        factory = RiskModelFactory()
        factory.register('mock', MockRiskModel)

        # Verify model is registered
        assert 'mock' in factory.list_models()

    def test_create_registered_model(self):
        """Test creating a model by name."""
        factory = RiskModelFactory()
        factory.register('mock', MockRiskModel)

        model = factory.create('mock')

        assert isinstance(model, MockRiskModel)
        assert model.param1 == 'default'
        assert model.param2 is None

    def test_list_models(self):
        """Test listing all registered model names."""
        factory = RiskModelFactory()
        factory.register('mock', MockRiskModel)
        factory.register('another', AnotherMockRiskModel)

        models = factory.list_models()

        assert 'mock' in models
        assert 'another' in models
        assert len(models) >= 2

    def test_create_unknown_model_raises(self):
        """Test that creating unknown model raises KeyError."""
        factory = RiskModelFactory()

        with pytest.raises(KeyError, match="Unknown risk model"):
            factory.create('nonexistent')

    def test_duplicate_registration(self):
        """Test that duplicate registration overwrites previous."""
        factory = RiskModelFactory()
        factory.register('model', MockRiskModel)
        factory.register('model', AnotherMockRiskModel)

        # Should use the second registration
        model = factory.create('model')
        assert isinstance(model, AnotherMockRiskModel)

    def test_create_with_kwargs(self):
        """Test passing kwargs to model constructor."""
        factory = RiskModelFactory()
        factory.register('mock', MockRiskModel)

        model = factory.create('mock', param1='custom', param2=42)

        assert isinstance(model, MockRiskModel)
        assert model.param1 == 'custom'
        assert model.param2 == 42

    def test_multiple_registrations(self):
        """Test registering multiple models."""
        factory = RiskModelFactory()
        factory.register('mock1', MockRiskModel)
        factory.register('mock2', AnotherMockRiskModel)

        model1 = factory.create('mock1')
        model2 = factory.create('mock2')

        assert isinstance(model1, MockRiskModel)
        assert isinstance(model2, AnotherMockRiskModel)

    def test_factory_is_singleton_or_instance(self):
        """Test that factory can be used as instance (not necessarily singleton)."""
        factory1 = RiskModelFactory()
        factory2 = RiskModelFactory()

        # Register in factory1
        factory1.register('model', MockRiskModel)

        # Should be isolated from factory2
        assert 'model' in factory1.list_models()
        # factory2 should have its own registry (no shared state)
        assert 'model' not in factory2.list_models()

    def test_unregister_model(self):
        """Test unregistering a model if supported."""
        factory = RiskModelFactory()
        factory.register('mock', MockRiskModel)

        # Verify registered
        assert 'mock' in factory.list_models()

        # Unregister
        factory.unregister('mock')

        # Should no longer be available
        assert 'mock' not in factory.list_models()

    def test_clear_registry(self):
        """Test clearing the registry if supported."""
        factory = RiskModelFactory()
        factory.register('mock1', MockRiskModel)
        factory.register('mock2', AnotherMockRiskModel)

        # Verify both registered
        assert len(factory.list_models()) >= 2

        # Clear registry
        factory.clear()

        # Should be empty
        assert len(factory.list_models()) == 0

    def test_get_model_class(self):
        """Test retrieving model class without instantiation."""
        factory = RiskModelFactory()
        factory.register('mock', MockRiskModel)

        model_class = factory.get_model_class('mock')

        assert model_class is MockRiskModel
        # Can instantiate manually
        model = model_class(param1='test')
        assert isinstance(model, MockRiskModel)
        assert model.param1 == 'test'

    def test_empty_registry(self):
        """Test list_models on empty registry."""
        factory = RiskModelFactory()

        models = factory.list_models()

        assert isinstance(models, list)
        assert len(models) == 0


class TestRiskModelFactoryErrorHandling:
    """Test error handling and edge cases."""

    def test_create_with_invalid_kwargs(self):
        """Test that invalid kwargs are passed through (let constructor handle)."""
        factory = RiskModelFactory()
        factory.register('mock', MockRiskModel)

        # MockRiskModel doesn't accept 'invalid_param'
        # Should raise TypeError from constructor
        with pytest.raises(TypeError):
            factory.create('mock', invalid_param='value')

    def test_unregister_unknown_model(self):
        """Test unregistering unknown model raises KeyError."""
        factory = RiskModelFactory()

        with pytest.raises(KeyError):
            factory.unregister('nonexistent')

    def test_get_model_class_unknown(self):
        """Test get_model_class for unknown model raises KeyError."""
        factory = RiskModelFactory()

        with pytest.raises(KeyError):
            factory.get_model_class('nonexistent')

    def test_register_with_none(self):
        """Test that registering None raises error."""
        factory = RiskModelFactory()

        with pytest.raises((TypeError, ValueError)):
            factory.register('model', None)


class TestRiskModelFactoryIntegration:
    """Test factory with realistic scenarios."""

    def test_multiple_instances_isolated(self):
        """Test that multiple factory instances have isolated registries."""
        factory1 = RiskModelFactory()
        factory2 = RiskModelFactory()

        factory1.register('model_a', MockRiskModel)
        factory2.register('model_b', AnotherMockRiskModel)

        # Each factory should only have its own models
        assert 'model_a' in factory1.list_models()
        assert 'model_a' not in factory2.list_models()
        assert 'model_b' in factory2.list_models()
        assert 'model_b' not in factory1.list_models()

    def test_register_overwrite_then_create(self):
        """Test overwriting registration and creating model."""
        factory = RiskModelFactory()
        factory.register('model', MockRiskModel)

        # Create first version
        model1 = factory.create('model')
        assert isinstance(model1, MockRiskModel)

        # Overwrite registration
        factory.register('model', AnotherMockRiskModel)

        # Create second version
        model2 = factory.create('model')
        assert isinstance(model2, AnotherMockRiskModel)
