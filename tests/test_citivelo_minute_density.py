r"""Asking whether a stored session can answer a minute-resolution question.

"Present in the store" is not "one-minute data available". On 2026-08-09 the
local ``USD-SOFR-1D-CITIVELOEXCELMIN`` asset held 1,233 days, of which 292 carry
fewer than 200 snapshots - a ten-minute era, on which "the curve at t-1min" is
not a request the data can answer. Nothing exposed that to a caller, and reading
the whole partition to find out costs ~21 ms for a number that is in the footer.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

from MDP.IRSwaps.CITIVELO_EXCEL.density import (
    DEFAULT_MAX_GAP,
    DayDensity,
    day_density,
    reset_density_cache,
)

ASSET = "USD-SOFR-1D-CITIVELOEXCELMIN"
DAY = datetime.date(2026, 6, 10)


class ParquetStore:
    """A store backed by real parquet, because the footer path is the point."""

    def __init__(self, base):
        self._base = base

    @property
    def base_dir(self):
        return self._base

    def raw_partition_dir(self, asset, day):
        return self._base / "raw" / f"asset={asset}" / f"date={day.isoformat()}"

    def has_day(self, asset, day):
        return self.raw_partition_dir(asset, day).exists()

    def write(self, asset, day, stamps_utc, *, filename="part.parquet"):
        d = self.raw_partition_dir(asset, day)
        d.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(stamps_utc, utc=True),
                # A realistic payload, so "reads the footer" is a claim with
                # something to be cheaper than.
                "nodes_json": ["{}" * 40] * len(stamps_utc),
            }
        )
        frame.to_parquet(d / filename, index=False)


@pytest.fixture()
def store(tmp_path):
    reset_density_cache()
    return ParquetStore(tmp_path)


def _minutes(day, start_h, n, step_min=1):
    base = pd.Timestamp(f"{day} {start_h:02d}:00", tz="UTC")
    return [base + pd.Timedelta(minutes=step_min * i) for i in range(n)]


def test_a_cold_day_is_absent_not_empty(store):
    d = day_density(store, ASSET, DAY)
    assert d.n_snapshots == 0 and d.present is False
    assert d.is_dense() is False


def test_a_dense_day_reports_its_shape(store):
    store.write(ASSET, DAY, _minutes("2026-06-10", 5, 900))
    d = day_density(store, ASSET, DAY)
    assert d.n_snapshots == 900
    assert d.max_gap_s == 60.0 and d.median_gap_s == 60.0
    assert d.is_dense() is True


def test_a_ten_minute_era_day_is_not_dense(store):
    store.write(ASSET, DAY, _minutes("2026-06-10", 5, 90, step_min=10))
    d = day_density(store, ASSET, DAY)
    assert d.n_snapshots == 90
    assert d.is_dense() is False, "90 snapshots cannot answer a t-1min request"


def test_a_count_alone_does_not_make_a_day_dense(store):
    """900 snapshots that stop before lunch are not 900 snapshots.

    This is the case a threshold on the count alone gets wrong, and it is not
    hypothetical - the Citi feed stops between ~11:58 and ~16:00 ET depending on
    the day.
    """
    stamps = _minutes("2026-06-10", 5, 449) + _minutes("2026-06-10", 18, 451)
    store.write(ASSET, DAY, stamps)
    d = day_density(store, ASSET, DAY)
    assert d.n_snapshots == 900
    assert d.max_gap_s > DEFAULT_MAX_GAP.total_seconds()
    assert d.is_dense() is False


def test_covers_answers_the_question_the_caller_actually_has(store):
    store.write(ASSET, DAY, _minutes("2026-06-10", 5, 420))  # 05:00 - 11:59 UTC
    d = day_density(store, ASSET, DAY)
    assert d.covers(pd.Timestamp("2026-06-10 09:00", tz="UTC")) is True
    assert d.covers(pd.Timestamp("2026-06-10 12:01", tz="UTC")) is True   # inside tolerance
    assert d.covers(pd.Timestamp("2026-06-10 15:00", tz="UTC")) is False  # feed had stopped
    assert d.covers(pd.Timestamp("2026-06-10 04:00", tz="UTC")) is False  # before it started


def test_covers_refuses_a_naive_instant(store):
    store.write(ASSET, DAY, _minutes("2026-06-10", 5, 10))
    d = day_density(store, ASSET, DAY)
    with pytest.raises(ValueError, match="tz-aware"):
        d.covers(pd.Timestamp("2026-06-10 09:00"))


def test_the_count_only_path_reads_no_timestamps(store, monkeypatch):
    """Asserts the READ, not just the result shape.

    "Returns None for the gap fields" is satisfied by a implementation that
    reads every column and then throws the answer away, which is the cost this
    module exists to avoid. So the column read is made to explode.
    """
    import pyarrow.parquet as pq

    store.write(ASSET, DAY, _minutes("2026-06-10", 5, 300))

    def _boom(*a, **kw):
        raise AssertionError("with_gaps=False must not read the timestamp column")

    monkeypatch.setattr(pq, "read_table", _boom)
    d = day_density(store, ASSET, DAY, with_gaps=False)
    assert d.n_snapshots == 300
    assert d.first_utc is None and d.max_gap_s is None
    # An unmeasured gap profile must not be reported as a satisfied gap bound.
    assert d.is_dense(min_snapshots=10) is False
    assert d.is_dense(min_snapshots=10, max_gap=None) is True


def test_multiple_files_in_one_partition_are_summed(store):
    store.write(ASSET, DAY, _minutes("2026-06-10", 5, 100), filename="a.parquet")
    store.write(ASSET, DAY, _minutes("2026-06-10", 8, 100), filename="b.parquet")
    assert day_density(store, ASSET, DAY).n_snapshots == 200
    assert day_density(store, ASSET, DAY, with_gaps=False).n_snapshots == 200


def test_an_appended_partition_invalidates_the_cache(store):
    """The intraday warmer appends minutes as they publish, mid-process.

    A density cached on first read would report a truncated session for the rest
    of a long run - the same silent staleness ``day_cache`` was built to avoid.
    """
    store.write(ASSET, DAY, _minutes("2026-06-10", 5, 100))
    assert day_density(store, ASSET, DAY).n_snapshots == 100
    store.write(ASSET, DAY, _minutes("2026-06-10", 5, 400))  # re-warm, same filename
    assert day_density(store, ASSET, DAY).n_snapshots == 400


def test_duplicate_stamps_are_counted_not_hidden(store):
    """Overlapping partitions after a re-warm really do produce these."""
    stamps = _minutes("2026-06-10", 5, 50)
    store.write(ASSET, DAY, stamps + stamps[:5])
    d = day_density(store, ASSET, DAY)
    assert d.n_snapshots == 55 and d.n_duplicate_stamps == 5


@pytest.mark.parametrize("has_the_day", [False, True])
def test_a_store_predating_raw_partition_dir_is_never_certified_dense(has_the_day):
    """``day_cache`` supports a store that cannot expose its partition path.

    Both branches, deliberately. ``has_day=False`` is the case where the right
    and the wrong answer coincide, so it proves nothing on its own. The one that
    matters is ``has_day=True``: the day EXISTS and its density is
    **unmeasurable**, and the module must report that as not-dense rather than
    guess. Reporting a day dense on the strength of a count it could not take
    would be the same class of defect as the read path this module supports.
    """

    class Ancient:
        base_dir = "nowhere"

        def has_day(self, asset, day):
            return has_the_day

    got = day_density(Ancient(), ASSET, DAY)
    assert got == DayDensity(asset=ASSET, local_date=DAY, n_snapshots=0)
    assert got.is_dense(min_snapshots=1) is False
    assert got.is_dense(min_snapshots=1, max_gap=None) is False
    assert got.covers(pd.Timestamp("2026-06-10 09:00", tz="UTC")) is False


def test_the_count_is_what_is_stored_not_what_the_read_path_serves(store, monkeypatch):
    """Stated as a bound, and pinned as one.

    ``CurveStore.read_raw_day`` applies the curve-sanity filter on the way out
    and can quarantine rows, so the footer count is an upper bound. Measured
    2026-08-09 the two agreed on 80 of 80 sampled days of the USD minute assets,
    but a helper that promised equality would be wrong the first time the filter
    fired - and it would be wrong in the optimistic direction.
    """
    store.write(ASSET, DAY, _minutes("2026-06-10", 5, 100))
    assert day_density(store, ASSET, DAY).n_snapshots == 100
