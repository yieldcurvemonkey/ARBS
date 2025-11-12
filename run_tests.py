#!/usr/bin/env python3
"""Simple test runner for sector rotation tests."""

import sys
import importlib.util

def run_test_file(test_file_path):
    """Load and run tests from a file."""
    spec = importlib.util.spec_from_file_location("test_module", test_file_path)
    test_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(test_module)

    # Find all test classes
    test_classes = [
        getattr(test_module, name)
        for name in dir(test_module)
        if name.startswith("Test")
    ]

    passed = 0
    failed = 0
    errors = []

    for test_class in test_classes:
        test_instance = test_class()
        test_methods = [m for m in dir(test_instance) if m.startswith("test_")]

        for method_name in test_methods:
            try:
                method = getattr(test_instance, method_name)
                method()
                print(f"✓ {test_class.__name__}.{method_name}")
                passed += 1
            except Exception as e:
                print(f"✗ {test_class.__name__}.{method_name}: {e}")
                failed += 1
                errors.append((test_class.__name__, method_name, str(e)))

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    if errors:
        print("\nFailures:")
        for class_name, method_name, error in errors:
            print(f"  {class_name}.{method_name}:")
            print(f"    {error}")

    return failed == 0

if __name__ == "__main__":
    test_file = sys.argv[1] if len(sys.argv) > 1 else "tests/unit/signals/sector_rotation/test_momentum_factor.py"
    success = run_test_file(test_file)
    sys.exit(0 if success else 1)
