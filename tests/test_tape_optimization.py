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

    def test_packages_enrichment_output_unchanged(self, golden):
        """_enrich_packages produces same output for package columns."""
        classified_df = golden["classified_df"].copy()
        raw_df = golden["raw_df"]
        tape = TradeTape(classified_df, raw_df=raw_df)

        # Run through prerequisites + prereq layers for packages
        df = tape._df.copy()
        df = tape._ensure_prerequisites(df)
        df = tape._enrich_classification(df)
        df = tape._enrich_upi_reference(df)
        df = tape._detect_off_date(df)
        df = tape._enrich_lifecycle(df)
        df = tape._enrich_cross_day_lifecycle(df)
        df = tape._enrich_event_type(df)
        df = tape._enrich_quality(df)
        df = tape._enrich_packages(df)

        # Compare package columns to golden
        pkg_cols = ["is_package", "has_spread", "n_package_legs",
                    "package_tenors", "package_structure"]
        enriched = golden["enriched"]
        expected = enriched[["trade_id"] + pkg_cols].set_index("trade_id").sort_index()
        actual = df[["trade_id"] + pkg_cols].set_index("trade_id").sort_index()

        pd.testing.assert_frame_equal(expected, actual, check_dtype=False)

    def test_full_compute_output_unchanged(self, golden):
        """Full compute() output matches golden snapshot."""
        classified_df = golden["classified_df"].copy()
        raw_df = golden["raw_df"]
        tape = TradeTape(classified_df, raw_df=raw_df)
        # use_cache=False so we exercise full pipeline
        if "use_cache" in TradeTape.compute.__code__.co_varnames:
            enriched = tape.compute(use_cache=False)
        else:
            enriched = tape.compute()

        expected = golden["enriched"].set_index("trade_id").sort_index()
        actual = enriched.set_index("trade_id").sort_index()

        # Check all columns exist
        assert set(expected.columns) == set(actual.columns), (
            f"Column mismatch: missing {set(expected.columns) - set(actual.columns)}, "
            f"extra {set(actual.columns) - set(expected.columns)}"
        )

        # Compare values column-by-column (full frame compare can be memory-heavy)
        for col in expected.columns:
            if col in {"tape_label"}:  # string col with complex formatting
                pd.testing.assert_series_equal(
                    expected[col], actual[col], check_dtype=False, check_names=False,
                )
            else:
                try:
                    pd.testing.assert_series_equal(
                        expected[col], actual[col], check_dtype=False, check_names=False,
                    )
                except AssertionError as e:
                    raise AssertionError(f"Column '{col}' differs: {e}") from e


class TestPartAPerformance:
    """Performance guardrails for Part A optimizations."""

    def test_cross_day_lifecycle_under_8s(self, golden):
        from SDRUtils.core.lifecycle import resolve_lifecycle_cross_day

        raw_df = golden["raw_df"]
        classified_ids = set(golden["classified_df"]["trade_id"].astype(str).values)

        t0 = time.perf_counter()
        resolve_lifecycle_cross_day(raw_df, classified_ids)
        elapsed = time.perf_counter() - t0
        assert elapsed < 8.0, f"cross-day lifecycle regressed to {elapsed:.2f}s (target <8s)"

    def test_packages_enrichment_under_1s(self, golden):
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
        df = tape._enrich_event_type(df)
        df = tape._enrich_quality(df)

        t0 = time.perf_counter()
        tape._enrich_packages(df)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"_enrich_packages regressed to {elapsed:.2f}s (target <1s)"

    def test_full_compute_under_15s(self, golden):
        classified_df = golden["classified_df"].copy()
        raw_df = golden["raw_df"]
        tape = TradeTape(classified_df, raw_df=raw_df)

        t0 = time.perf_counter()
        # use_cache=False once available; otherwise just compute()
        if "use_cache" in TradeTape.compute.__code__.co_varnames:
            tape.compute(use_cache=False)
        else:
            tape.compute()
        elapsed = time.perf_counter() - t0
        assert elapsed < 15.0, f"full compute() regressed to {elapsed:.2f}s (target <15s)"
