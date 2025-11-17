#!/usr/bin/env python3
# ABOUTME: Basic workflow validation test for ARBS setup
# ABOUTME: Verifies dependencies, imports, and basic functionality without requiring market data

"""
Basic Workflow Test for ARBS

This script validates the ARBS development environment is set up correctly.
It tests imports, query creation, arithmetic, and basic functionality.

Usage:
    python test_basic_workflow.py

Expected output:
    ✓ Python version check
    ✓ Core dependencies (numpy, pandas, QuantLib, rateslib)
    ✓ Query creation and arithmetic
    ✓ MDP request building
    ✓ Curve definitions lookup
    ✓ All checks passed!

This should run in <5 seconds without requiring market data.
"""

import sys
from typing import Dict, Any


def check_python_version() -> bool:
    """Verify Python version is 3.12+"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 12):
        print(f"✗ Python {version.major}.{version.minor} detected, requires 3.12+")
        return False
    print(f"✓ Python {version.major}.{version.minor}.{version.micro}")
    return True


def check_core_dependencies() -> bool:
    """Verify core scientific computing libraries"""
    try:
        import numpy as np
        import pandas as pd
        import QuantLib as ql
        import rateslib as rl

        print(f"✓ numpy {np.__version__}")
        print(f"✓ pandas {pd.__version__}")
        print(f"✓ QuantLib {ql.__version__}")
        print(f"✓ rateslib {rl.__version__}")
        return True
    except ImportError as e:
        print(f"✗ Missing dependency: {e}")
        print("  Run: pip install -r requirements.txt")
        return False


def check_arbs_imports() -> bool:
    """Verify ARBS modules can be imported"""
    try:
        # Add current directory to path if needed
        if '.' not in sys.path:
            sys.path.insert(0, '.')

        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapStructure import IRSwapStructure
        from Query.IRSwaps.IRSwapValue import IRSwapValue
        from BT.query_engine import QueryDrivenBacktest
        from MDP.MarketDataProvider import MarketDataProvider
        from definitions.IRSwaps import CURVE_DEFINITIONS

        print("✓ ARBS core modules")
        return True
    except ImportError as e:
        print(f"✗ ARBS import error: {e}")
        print("  Ensure you are in the ARBS root directory")
        return False


def check_query_creation() -> bool:
    """Test query creation"""
    try:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapStructure import IRSwapStructure
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        # Create a simple query
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000}
        )

        assert query.tenor == "5Y", "Query tenor mismatch"
        assert query.curve == "USD-SOFR-1D", "Query curve mismatch"
        assert query.structure == IRSwapStructure.OUTRIGHT, "Query structure mismatch"

        print("✓ Query creation")
        return True
    except Exception as e:
        print(f"✗ Query creation failed: {e}")
        return False


def check_query_arithmetic() -> bool:
    """Test query arithmetic operations"""
    try:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapStructure import IRSwapStructure
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        # Create queries
        q_2y = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="2Y",
            curve="USD-SOFR-1D"
        )
        q_3y = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="3Y",
            curve="USD-SOFR-1D"
        )
        q_5y = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="5Y",
            curve="USD-SOFR-1D"
        )

        # Test arithmetic: fly = 2Y + 5Y - 2*3Y
        fly = q_2y + q_5y - 2 * q_3y
        assert isinstance(fly, list), "Fly should be a list of queries"
        assert len(fly) == 3, f"Fly should have 3 legs, got {len(fly)}"

        print("✓ Query arithmetic (fly structure)")
        return True
    except Exception as e:
        print(f"✗ Query arithmetic failed: {e}")
        return False


def check_mdp_request_building() -> bool:
    """Test MDP request building"""
    try:
        import datetime
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapStructure import IRSwapStructure
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="5Y",
            curve="USD-SOFR-1D"
        )

        # Build MDP request
        now = datetime.datetime(2024, 1, 15, 15, 0, 0)
        request = query.build_mdp_request(now)

        assert isinstance(request, dict), "MDP request should be a dict"
        assert "curve_name" in request, "MDP request should have curve_name"
        assert request["curve_name"] == "USD-SOFR-1D", "Curve name mismatch"
        assert "timestamp" in request, "MDP request should have timestamp"

        print("✓ MDP request building")
        return True
    except Exception as e:
        print(f"✗ MDP request building failed: {e}")
        return False


def check_curve_definitions() -> bool:
    """Test curve definitions lookup"""
    try:
        from definitions.IRSwaps import CURVE_DEFINITIONS

        assert isinstance(CURVE_DEFINITIONS, dict), "CURVE_DEFINITIONS should be a dict"
        assert len(CURVE_DEFINITIONS) > 0, "CURVE_DEFINITIONS should not be empty"
        assert "USD-SOFR-1D" in CURVE_DEFINITIONS, "USD-SOFR-1D should be in definitions"

        # Check a few expected curves
        expected_curves = ["USD-SOFR-1D", "USD-FEDFUNDS", "USD-OIS"]
        found_curves = [c for c in expected_curves if c in CURVE_DEFINITIONS]

        print(f"✓ Curve definitions ({len(CURVE_DEFINITIONS)} curves available)")
        print(f"  Found: {', '.join(found_curves[:5])}")
        return True
    except Exception as e:
        print(f"✗ Curve definitions lookup failed: {e}")
        return False


def check_frozen_dataclass_behavior() -> bool:
    """Test frozen dataclass (immutability)"""
    try:
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapStructure import IRSwapStructure
        from Query.IRSwaps.IRSwapValue import IRSwapValue
        from dataclasses import replace

        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="5Y",
            curve="USD-SOFR-1D"
        )

        # Test immutability
        try:
            query.tenor = "10Y"
            print("✗ Query should be immutable (frozen dataclass)")
            return False
        except Exception:
            pass  # Expected - frozen dataclass

        # Test replace() works
        query_10y = replace(query, tenor="10Y")
        assert query_10y.tenor == "10Y", "Replace should work"
        assert query.tenor == "5Y", "Original should be unchanged"

        print("✓ Frozen dataclass behavior (immutability)")
        return True
    except Exception as e:
        print(f"✗ Frozen dataclass test failed: {e}")
        return False


def main() -> int:
    """Run all validation checks"""
    print("="* 60)
    print("ARBS Basic Workflow Validation")
    print("="* 60)
    print()

    checks = [
        ("Python version", check_python_version),
        ("Core dependencies", check_core_dependencies),
        ("ARBS imports", check_arbs_imports),
        ("Query creation", check_query_creation),
        ("Query arithmetic", check_query_arithmetic),
        ("MDP request building", check_mdp_request_building),
        ("Curve definitions", check_curve_definitions),
        ("Frozen dataclass", check_frozen_dataclass_behavior),
    ]

    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append(result)
        except Exception as e:
            print(f"✗ {name} - Unexpected error: {e}")
            results.append(False)
        print()

    print("="* 60)
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"✓ All {total} checks passed!")
        print()
        print("Your ARBS environment is ready to use.")
        print("Next steps:")
        print("  - Run example notebooks: jupyter notebook")
        print("  - Explore strategies: ls strategies/examples/")
        print("  - Read docs: cat docs/QUICKSTART.md")
        return 0
    else:
        print(f"✗ {total - passed} of {total} checks failed")
        print()
        print("Please fix the issues above and try again.")
        print("Common fixes:")
        print("  - Install dependencies: pip install -r requirements.txt")
        print("  - Ensure Python 3.12+: python --version")
        print("  - Run from ARBS root directory")
        return 1


if __name__ == "__main__":
    sys.exit(main())
