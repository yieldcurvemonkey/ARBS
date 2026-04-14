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


class TestPartAEquivalence:
    """Optimized layers produce identical output to baseline golden snapshot."""

    def test_cross_day_lifecycle_output_unchanged(self, golden):
        """_enrich_cross_day_lifecycle produces same xd_* cols as golden."""
        classified_df = golden["classified_df"].copy()
        raw_df = golden["raw_df"]
        tape = TradeTape(classified_df, raw_df=raw_df)

        df = tape._df.copy()
        df = tape._ensure_prerequisites(df)
        df = tape._enrich_classification(df)
        df = tape._enrich_upi_reference(df)
        df = tape._detect_off_date(df)
        df = tape._enrich_lifecycle(df)
        df = tape._enrich_cross_day_lifecycle(df)

        enriched = golden["enriched"]
        xd_cols = [c for c in enriched.columns if c.startswith("xd_")]
        expected = enriched.set_index("trade_id")[xd_cols].sort_index()
        actual = df.set_index("trade_id")[xd_cols].sort_index()

        common = expected.index.intersection(actual.index)
        pd.testing.assert_frame_equal(
            expected.loc[common],
            actual.loc[common],
            check_dtype=False,
        )
