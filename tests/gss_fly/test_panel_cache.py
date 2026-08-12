"""The panel cache must survive an interruption, and a resumed panel must equal a fresh one.

Building the GSS curve panel is I/O-bound on an upstream that stalls for minutes at a time, so a
507-day panel takes about an hour at single-digit CPU. Writing the cache only at the end meant any
interruption in that hour discarded every completed day. These tests pin the two properties that
make the per-day cache worth having:

1. **It resumes.** A second run refetches only the days the first run did not finish.
2. **It resumes to the same answer.** An interrupted-then-resumed panel is identical, value for
   value, to one built in a single pass. A resume that assembles differently is a resume that
   silently changes the result — the failure mode a cache is most likely to introduce and least
   likely to announce.

The fake source counts its own calls, so "did not refetch" is measured rather than assumed.
"""

from __future__ import annotations

import datetime
import time

import numpy as np
import pandas as pd
import pytest

from BT.gss_fly.data import build_curve_panel

CUSIPS = ["912810AA1", "912810BB2", "912810CC3", "912810DD4"]


class _Spline:
    def __init__(self, day_index: int):
        self._i = day_index
        self.rmse = 1.0 + 0.01 * day_index
        self.yield_errors = pd.Series(1.0, index=CUSIPS)

    def to_frame(self) -> pd.DataFrame:
        n = len(CUSIPS)
        return pd.DataFrame(
            {
                # deterministic but day-dependent, so a day served from cache that belongs to a
                # different day would show up as a value mismatch rather than passing silently
                "yield_error_bp": [self._i + 0.1 * k for k in range(n)],
                "observed": [4.0 + 0.01 * self._i + 0.001 * k for k in range(n)],
                "ttm": [2.0, 5.0, 10.0, 30.0],
            },
            index=pd.Index(CUSIPS, name="cusip"),
        )


class _FakeMDP:
    """Counts fetches, and can be told to fail from a given day onward."""

    def __init__(self, dates, fail_from: int | None = None):
        self._order = {d: i for i, d in enumerate(dates)}
        self.fail_from = fail_from
        self.spline_calls: list[datetime.date] = []
        self.ref_calls: list[datetime.date] = []

    def _guard(self, d):
        i = self._order[d]
        if self.fail_from is not None and i >= self.fail_from:
            raise RuntimeError(f"upstream stalled on {d}")
        return i

    def fetch_cash_spline(self, d):
        self.spline_calls.append(d)
        return _Spline(self._guard(d))

    def get_bond_reference_data(self, as_of_date):
        self.ref_calls.append(as_of_date)
        i = self._guard(as_of_date)
        return pd.DataFrame(
            {
                "cusip": CUSIPS,
                "ttm": [2.0, 5.0, 10.0, 30.0],
                "cpn": [4.0, 4.25, 4.5, 4.75],
                "rank": [0, 1, 1, 1],
                "maturity_date": [
                    pd.Timestamp(as_of_date) + pd.DateOffset(years=y) for y in (2, 5, 10, 30)
                ],
                "issue_date": [pd.Timestamp(as_of_date) - pd.Timedelta(days=200 + i)] * 4,
            }
        )


@pytest.fixture
def dates():
    return [d.date() for d in pd.bdate_range("2025-01-02", periods=8)]


def test_a_completed_day_is_written_before_the_run_ends(tmp_path, dates):
    """The point of the change: days land on disk as they complete, not at the end."""
    mdp = _FakeMDP(dates, fail_from=5)
    build_curve_panel(dates, mdp, cache_path=tmp_path / "panel", show_progress=False)
    written = sorted(p.name for p in (tmp_path / "panel" / "days").glob("*.spline.parquet"))
    assert len(written) == 5, written
    # and the consolidated cache is NOT claimed, because the panel is incomplete
    assert not (tmp_path / "panel" / "s2c.parquet").exists() or len(written) == len(dates)


def test_resume_refetches_only_the_missing_days(tmp_path, dates):
    cache = tmp_path / "panel"

    first = _FakeMDP(dates, fail_from=5)
    build_curve_panel(dates, first, cache_path=cache, show_progress=False)
    assert len(first.spline_calls) == len(dates)  # it tried them all, 5 succeeded

    second = _FakeMDP(dates)  # upstream healthy now
    build_curve_panel(dates, second, cache_path=cache, show_progress=False)
    assert sorted(second.spline_calls) == sorted(dates[5:]), second.spline_calls
    assert sorted(second.ref_calls) == sorted(dates[5:]), second.ref_calls


def test_resumed_panel_is_identical_to_one_built_in_a_single_pass(tmp_path, dates):
    """The property that matters. Interrupt, resume, and compare against an uninterrupted build."""
    cache = tmp_path / "panel"
    build_curve_panel(dates, _FakeMDP(dates, fail_from=5), cache_path=cache, show_progress=False)
    resumed = build_curve_panel(dates, _FakeMDP(dates), cache_path=cache, show_progress=False)

    fresh = build_curve_panel(dates, _FakeMDP(dates), cache_path=tmp_path / "fresh", show_progress=False)

    pd.testing.assert_frame_equal(resumed.s2c, fresh.s2c)
    pd.testing.assert_frame_equal(resumed.ytm, fresh.ytm)
    pd.testing.assert_frame_equal(resumed.ttm, fresh.ttm)
    pd.testing.assert_series_equal(resumed.rmse, fresh.rmse)
    # reference rows may be assembled cached-first, so compare as sets of rows
    key = ["date", "cusip"]
    a = resumed.reference.sort_values(key).reset_index(drop=True)
    b = fresh.reference.sort_values(key).reset_index(drop=True)
    pd.testing.assert_frame_equal(a[b.columns], b)


def test_the_test_would_notice_a_cache_serving_the_wrong_day(tmp_path, dates):
    """Guard on the guard: the fixture's values are day-dependent, so a mismatch is detectable.

    If `_Spline` returned the same numbers every day, the identity test above would pass even for a
    cache that served day 3's file for day 6. Confirm the values actually differ by day.
    """
    a = _Spline(0).to_frame()["yield_error_bp"].to_numpy()
    b = _Spline(5).to_frame()["yield_error_bp"].to_numpy()
    assert not np.allclose(a, b)


def test_a_corrupt_cached_day_is_refetched_not_fatal(tmp_path, dates):
    cache = tmp_path / "panel"
    build_curve_panel(dates, _FakeMDP(dates, fail_from=5), cache_path=cache, show_progress=False)

    victim = sorted((cache / "days").glob("*.spline.parquet"))[0]
    victim.write_bytes(b"not a parquet file")

    mdp = _FakeMDP(dates)
    panel = build_curve_panel(dates, mdp, cache_path=cache, show_progress=False)
    assert len(panel.s2c) == len(dates)
    # the corrupt day is among those refetched
    assert len(mdp.spline_calls) == len(dates) - 4


def test_a_chunked_warm_never_bakes_a_prefix_as_the_whole_panel(tmp_path, dates):
    """The trap on the other side of the same defect.

    A chunked warm calls the builder on growing prefixes. Every prefix resolves completely, so
    under `consolidate="complete"` the first chunk would write a consolidated cache of 2 days —
    and the consolidated file wins on read, so every later chunk, and the backtest after them,
    would be served those 2 days as if they were the whole range.
    """
    cache = tmp_path / "panel"
    mdp = _FakeMDP(dates)
    for end in (2, 4, 6, 8):
        build_curve_panel(dates[:end], mdp, cache_path=cache, show_progress=False, consolidate="never")
        assert not (cache / "s2c.parquet").exists(), f"prefix of {end} consolidated"

    panel = build_curve_panel(dates, mdp, cache_path=cache, show_progress=False)
    assert (cache / "s2c.parquet").exists()
    assert len(panel.s2c) == len(dates)
    assert len(mdp.spline_calls) == len(dates), "the chunked warm should have fetched each day once"


def test_consolidate_rejects_an_unknown_mode(tmp_path, dates):
    with pytest.raises(ValueError):
        build_curve_panel(dates, _FakeMDP(dates), cache_path=tmp_path / "p", consolidate="partial")


def test_consolidate_always_bakes_a_panel_with_real_gaps(tmp_path, dates):
    cache = tmp_path / "panel"
    build_curve_panel(dates, _FakeMDP(dates, fail_from=5), cache_path=cache,
                      show_progress=False, consolidate="always")
    assert (cache / "s2c.parquet").exists()
    served = build_curve_panel(dates, _FakeMDP(dates), cache_path=cache, show_progress=False)
    assert len(served.s2c) == 5


class _JitteredMDP(_FakeMDP):
    """Finishes days out of order, so a builder that absorbed by completion order would differ.

    Without this the parallel-equals-serial test is worthless: if every day took the same time the
    pool would happen to complete them in order and the test would pass for a builder that has no
    ordering guarantee at all.
    """

    def fetch_cash_spline(self, d):
        i = self._order[d]
        # later days return fastest, so completion order is close to reversed
        time.sleep(0.02 * (len(self._order) - i))
        return super().fetch_cash_spline(d)


def test_parallel_fetch_equals_serial(tmp_path, dates):
    serial = build_curve_panel(dates, _JitteredMDP(dates), cache_path=tmp_path / "s", show_progress=False)
    par = build_curve_panel(dates, _JitteredMDP(dates), cache_path=tmp_path / "p",
                            show_progress=False, workers=4)

    pd.testing.assert_frame_equal(par.s2c, serial.s2c)
    pd.testing.assert_frame_equal(par.ytm, serial.ytm)
    pd.testing.assert_frame_equal(par.ttm, serial.ttm)
    pd.testing.assert_series_equal(par.rmse, serial.rmse)
    # row-for-row, in the same order — not merely the same set
    pd.testing.assert_frame_equal(par.reference, serial.reference)


def test_the_jitter_actually_reorders_completions():
    """Guard on the guard: prove the pool really does finish these days out of order."""
    from concurrent.futures import ThreadPoolExecutor

    ds = [d.date() for d in pd.bdate_range("2025-01-02", periods=8)]
    mdp = _JitteredMDP(ds)
    done: list = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda d: (mdp.fetch_cash_spline(d), done.append(d)), ds))
    assert done != ds, "days completed in submission order — the ordering test proves nothing"


def test_parallel_fetch_still_skips_cached_days(tmp_path, dates):
    cache = tmp_path / "panel"
    build_curve_panel(dates, _FakeMDP(dates, fail_from=5), cache_path=cache,
                      show_progress=False, workers=4)
    mdp = _FakeMDP(dates)
    build_curve_panel(dates, mdp, cache_path=cache, show_progress=False, workers=4)
    assert sorted(mdp.spline_calls) == sorted(dates[5:])


def test_consolidated_cache_short_circuits_the_day_scan(tmp_path, dates):
    cache = tmp_path / "panel"
    build_curve_panel(dates, _FakeMDP(dates), cache_path=cache, show_progress=False)
    assert (cache / "s2c.parquet").exists()

    again = _FakeMDP(dates)
    panel = build_curve_panel(dates, again, cache_path=cache, show_progress=False)
    assert again.spline_calls == []
    assert len(panel.s2c) == len(dates)
