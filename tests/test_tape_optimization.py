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


class TestCacheKey:
    """Cache key is deterministic and sensitive to relevant inputs."""

    def _make_df(self, n=3):
        return pd.DataFrame({
            "trade_id": [f"T{i}" for i in range(n)],
            "execution_timestamp": pd.to_datetime(
                [f"2026-03-0{i+1} 14:00:00+00:00" for i in range(n)]
            ),
            "event_action": ["NEWT-TRAD"] * n,
            "event_type": ["TRAD"] * n,
            "tenor_years": [5.0 + i for i in range(n)],
            "notional": [10_000_000 * (i + 1) for i in range(n)],
        })

    def test_identical_inputs_produce_same_key(self):
        df = self._make_df()
        k1 = TradeTape(df)._cache_key()
        k2 = TradeTape(df.copy())._cache_key()
        assert k1 == k2

    def test_different_trade_ids_produce_different_keys(self):
        df1 = self._make_df()
        df2 = df1.copy()
        df2.loc[0, "trade_id"] = "X1"
        assert TradeTape(df1)._cache_key() != TradeTape(df2)._cache_key()

    def test_config_change_produces_different_key(self):
        df = self._make_df()
        k1 = TradeTape(df, cluster_gap_seconds=120)._cache_key()
        k2 = TradeTape(df, cluster_gap_seconds=60)._cache_key()
        assert k1 != k2

    def test_raw_df_presence_changes_key(self):
        df = self._make_df()
        k1 = TradeTape(df)._cache_key()
        k2 = TradeTape(df, raw_df=df.copy())._cache_key()
        assert k1 != k2

    def test_version_bump_invalidates_key(self, monkeypatch):
        from SDRUtils.analytics import trade_tape as tt_module
        df = self._make_df()
        k1 = TradeTape(df)._cache_key()
        monkeypatch.setattr(tt_module, "TRADE_TAPE_CACHE_VERSION", "v999")
        k2 = TradeTape(df)._cache_key()
        assert k1 != k2


class TestCacheLoadSave:
    """_save_cache and _try_load_cache round-trip."""

    def test_save_and_load_round_trip(self, tmp_path):
        df = pd.DataFrame({
            "trade_id": ["A", "B"],
            "execution_timestamp": pd.to_datetime(
                ["2026-03-01 14:00:00+00:00", "2026-03-02 14:00:00+00:00"]
            ),
            "tenor_years": [5.0, 10.0],
            "notional": [10_000_000, 20_000_000],
        })
        tape = TradeTape(df)
        result_df = df.copy()
        result_df["enriched_col"] = [1, 2]

        tape._save_cache(result_df, cache_dir=str(tmp_path))
        loaded = tape._try_load_cache(cache_dir=str(tmp_path))

        assert loaded is not None
        pd.testing.assert_frame_equal(result_df, loaded)

    def test_load_miss_returns_none(self, tmp_path):
        df = pd.DataFrame({
            "trade_id": ["A"],
            "execution_timestamp": pd.to_datetime(["2026-03-01 14:00:00+00:00"]),
            "tenor_years": [5.0],
            "notional": [10_000_000],
        })
        tape = TradeTape(df)
        assert tape._try_load_cache(cache_dir=str(tmp_path)) is None

    def test_corrupted_cache_returns_none(self, tmp_path):
        df = pd.DataFrame({
            "trade_id": ["A"],
            "execution_timestamp": pd.to_datetime(["2026-03-01 14:00:00+00:00"]),
            "tenor_years": [5.0],
            "notional": [10_000_000],
        })
        tape = TradeTape(df)
        # Write garbage at the key location
        key = tape._cache_key()
        corrupt_path = tmp_path / f"{key}.pkl"
        corrupt_path.write_bytes(b"not a valid pickle stream")
        assert tape._try_load_cache(cache_dir=str(tmp_path)) is None


class TestComputeCaching:
    """compute() with use_cache=True writes and reads cache."""

    def _sample_tape(self, golden):
        classified_df = golden["classified_df"].copy()
        raw_df = golden["raw_df"]
        return TradeTape(classified_df, raw_df=raw_df)

    def test_cache_hit_skips_pipeline(self, golden, tmp_path):
        # First compute: miss, writes cache
        tape1 = self._sample_tape(golden)
        out1 = tape1.compute(use_cache=True, cache_dir=str(tmp_path))

        # Second compute: hit, reads from disk (fast)
        tape2 = self._sample_tape(golden)
        t0 = time.perf_counter()
        out2 = tape2.compute(use_cache=True, cache_dir=str(tmp_path))
        elapsed = time.perf_counter() - t0

        assert elapsed < 2.0, f"cached compute took {elapsed:.2f}s (should be <2s)"
        pd.testing.assert_frame_equal(
            out1.set_index("trade_id").sort_index(),
            out2.set_index("trade_id").sort_index(),
            check_dtype=False,
        )

    def test_use_cache_false_does_not_write(self, golden, tmp_path):
        tape = self._sample_tape(golden)
        tape.compute(use_cache=False, cache_dir=str(tmp_path))
        # tmp_path should be empty (no files written)
        assert list(tmp_path.iterdir()) == []

    def test_clear_cache_removes_files(self, golden, tmp_path):
        tape = self._sample_tape(golden)
        tape.compute(use_cache=True, cache_dir=str(tmp_path))
        assert len(list(tmp_path.iterdir())) == 1

        n_deleted = TradeTape.clear_cache(cache_dir=str(tmp_path))
        assert n_deleted == 1
        assert list(tmp_path.iterdir()) == []
