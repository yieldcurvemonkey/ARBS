"""Optimization regression tests — Part A (correctness) and Part B (caching).

Part A tests depend on tests/fixtures/tape_golden_mar_2_6.pkl — build via
tests/fixtures/build_tape_golden.py before running.
"""
import os
import pickle
import time
import pytest
import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape

GOLDEN_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "tape_golden_mar_2_6.pkl"
)


@pytest.fixture(scope="module")
def golden():
    """Load the pre-optimization golden snapshot."""
    if not os.path.exists(GOLDEN_PATH):
        pytest.skip(f"Golden snapshot not built: {GOLDEN_PATH}")
    with open(GOLDEN_PATH, "rb") as f:
        return pickle.load(f)
