import datetime
import threading
import uuid
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from Caching.computed_timeseries_store import ComputedTimeseriesStore
from MDP.MarketDataProvider import MarketDataProvider
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from TB.FixedRateBondsTB import FixedRateBondsTB
from TB.IRSwapsTB import IRSwapsTB


class _FakeIRSwapsMDP(MarketDataProvider):
    def __init__(self, source: str):
        super().__init__(source=source)
        self.bulk_calls = 0

    def get_pricer(self, request: Dict[str, Any]) -> Any:
        return request

    def bulk_get_data(self, request: Dict[str, Any]) -> Dict[Any, Any]:
        self.bulk_calls += 1
        return {ts: {"curve": ts} for ts in request["timestamps"]}


class _FakeFixedRateBondsMDP(MarketDataProvider):
    def __init__(self, source: str):
        super().__init__(source=source)
        self.bulk_calls = 0
        self.bulk_timestamps: list[list[Any]] = []

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def bulk_get_data(
        self,
        timestamps,
        cusips,
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
        max_workers: int = 8,
    ) -> Dict[Any, Dict[str, Any]]:
        _ = show_tqdm, force_refresh, max_workers
        self.bulk_calls += 1
        self.bulk_timestamps.append(list(timestamps))
        return {ts: {cusip: {"cusip": cusip, "timestamp": ts} for cusip in cusips} for ts in timestamps}


class _ProbeRecordingCache(dict):
    def __init__(self):
        super().__init__()
        self._l2_read = True
        self._l2_write = True
        self.contains_flags: list[bool] = []

    def __contains__(self, key):
        self.contains_flags.append(bool(self._l2_read))
        return super().__contains__(key)


class _YTMPricer:
    def __init__(self, value: float):
        self._value = float(value)

    def ytm(self) -> float:
        return self._value


def test_computed_timeseries_store_default_base_dir_is_repo_root_relative(monkeypatch, tmp_path):
    import Caching.computed_timeseries_store as cts_module

    cwd = tmp_path / "nested" / "cwd"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)

    expected = Path(cts_module.__file__).resolve().parents[1] / "data" / "ts"

    store = ComputedTimeseriesStore(use_duckdb=False)
    assert Path(store.write_options.base_dir).resolve() == expected.resolve()

    router = IRSwapsTB(_FakeIRSwapsMDP(source="TEST_IRS_DEFAULT_BASE"), show_tqdm=False, use_duckdb=False)
    assert Path(router._computed_ts_store.write_options.base_dir).resolve() == expected.resolve()


def test_computed_timeseries_store_wait_for_background_pushes_joins_pending_tasks(monkeypatch, tmp_path):
    import Caching.computed_timeseries_store as cts_module

    started = threading.Event()
    release = threading.Event()
    push_calls: list[tuple[str, Any]] = []

    class _FakeSync:
        def push_day(self, symbol, trading_date):
            push_calls.append(("day", trading_date))
            started.set()
            assert release.wait(timeout=2.0)

        def push_rows(self, symbol, rows):
            push_calls.append(("rows", tuple(rows)))
            started.set()
            assert release.wait(timeout=2.0)

    monkeypatch.setattr(cts_module, "_get_computed_ts_sync", lambda base_dir: _FakeSync())

    store = ComputedTimeseriesStore(base_dir=tmp_path, use_duckdb=False)
    # EOD row: both L2 pushes (whole-day blob + row-level value) apply. An
    # intraday row deliberately skips the row-level push -- that table is keyed
    # (symbol, trading_date) and would collapse a day onto one minute; see
    # test_intraday_rows_do_not_touch_date_keyed_tiers.
    ts = datetime.date(2025, 1, 6)

    store.append_rows(
        symbol="IRS::WAIT_TEST",
        rows=[
            (ts, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
        ],
    )

    assert started.wait(timeout=1.0)
    release.set()
    waited = store.wait_for_background_pushes(timeout=2.0)

    assert waited == 2
    assert store.wait_for_background_pushes(timeout=0.0) == 0
    assert sorted(kind for kind, _ in push_calls) == ["day", "rows"]


def test_intraday_rows_do_not_touch_date_keyed_tiers(monkeypatch, tmp_path):
    """An intraday build must not overwrite the EOD value of the same symbol.

    The DuckDB table and the row-level L2 table are keyed (symbol, trading_date).
    Writing intraday points into them collapsed a whole day onto one arbitrary
    minute, which the next daily-frequency read then served as that day's value.
    """
    import Caching.computed_timeseries_store as cts_module

    push_kinds: list[str] = []

    class _FakeSync:
        def push_day(self, symbol, trading_date):
            push_kinds.append("day")

        def push_rows(self, symbol, rows):
            push_kinds.append("rows")

    monkeypatch.setattr(cts_module, "_get_computed_ts_sync", lambda base_dir: _FakeSync())

    store = ComputedTimeseriesStore(base_dir=tmp_path)
    sym = "IRS::INTRADAY_GUARD"
    col = "USD-SOFR-1D 5Y OUTRIGHT RATE"
    day = datetime.date(2025, 1, 6)

    store.append_rows(symbol=sym, rows=[(day, col, 4.000)])          # EOD
    store.wait_for_background_pushes(timeout=2.0)
    push_kinds.clear()

    store.append_rows(                                                # intraday
        symbol=sym,
        rows=[
            (datetime.datetime(2025, 1, 6, h, m, tzinfo=datetime.timezone.utc), col, v)
            for (h, m), v in [((14, 30), 4.100), ((20, 59), 4.190)]
        ],
    )
    store.wait_for_background_pushes(timeout=2.0)

    # the EOD slot is untouched
    eod = store.read_rows(
        symbol=sym, reference_points=[day], intraday=False, skip_current_eod=False,
        fallback_column_name=col, allow_partial=True,
    )
    assert eod and eod[0][2] == 4.000

    # the row-level L2 push is skipped; the whole-day blob still goes
    assert "rows" not in push_kinds
    assert "day" in push_kinds

    # and the intraday points themselves round-trip at full resolution
    got = store.read_rows(
        symbol=sym,
        reference_points=[
            datetime.datetime(2025, 1, 6, 14, 30, tzinfo=datetime.timezone.utc),
            datetime.datetime(2025, 1, 6, 20, 59, tzinfo=datetime.timezone.utc),
        ],
        intraday=True, skip_current_eod=False, fallback_column_name=col, allow_partial=True,
    )
    assert [round(v, 6) for _d, _c, v in got] == [4.100, 4.190]


def test_computed_timeseries_store_roundtrip_preserves_intraday_column_names(tmp_path):
    store = ComputedTimeseriesStore(base_dir=tmp_path)
    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)

    store.append_rows(
        symbol="IRS::TEST",
        rows=[
            (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
            (ts2, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.052),
        ],
    )

    rows = store.read_rows(
        symbol="IRS::TEST",
        reference_points=[ts1, ts2],
        intraday=True,
        skip_current_eod=False,
        fallback_column_name="fallback",
    )

    assert rows == [
        (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
        (ts2, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.052),
    ]


def test_computed_timeseries_store_compacts_day_partition_on_rewrite(tmp_path):
    store = ComputedTimeseriesStore(base_dir=tmp_path)
    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)

    store.append_rows(
        symbol="IRS::TEST_COMPACT",
        rows=[
            (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
        ],
    )
    store.append_rows(
        symbol="IRS::TEST_COMPACT",
        rows=[
            (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.052),
            (ts2, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.053),
        ],
    )

    part_dir = tmp_path / "asset=IRS__TEST_COMPACT" / "date=2025-01-06"
    assert len(list(part_dir.glob("*.parquet"))) == 1

    rows = store.read_rows(
        symbol="IRS::TEST_COMPACT",
        reference_points=[ts1, ts2],
        intraday=True,
        skip_current_eod=False,
        fallback_column_name="fallback",
    )

    assert rows == [
        (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.052),
        (ts2, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.053),
    ]


def test_computed_timeseries_store_skips_redundant_per_day_remote_probe_for_absent_local_days(monkeypatch, tmp_path):
    import Caching.computed_timeseries_store as cts_module

    store = ComputedTimeseriesStore(base_dir=tmp_path)
    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 7, 14, 0, tzinfo=datetime.timezone.utc)

    store.append_rows(
        symbol="IRS::TEST_REMOTE_PROBE",
        rows=[
            (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
        ],
    )

    class _FakeSync:
        def __init__(self):
            self.prefetch_calls = []
            self.pull_calls = []

        def prefetch_range(self, symbol, start, end):
            self.prefetch_calls.append((symbol, start, end))
            return []

        def pull_days_batch(self, symbol, trading_dates):
            return []

        def pull_day(self, symbol, trading_date):
            self.pull_calls.append((symbol, trading_date))
            return False

    fake_sync = _FakeSync()
    monkeypatch.setattr(cts_module, "_get_computed_ts_sync", lambda base_dir: fake_sync)

    rows = store.read_rows(
        symbol="IRS::TEST_REMOTE_PROBE",
        reference_points=[ts1, ts2],
        intraday=True,
        skip_current_eod=False,
        fallback_column_name="fallback",
    )

    assert rows == [
        (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
    ]
    assert len(fake_sync.prefetch_calls) == 1
    assert fake_sync.pull_calls == []


def test_computed_timeseries_store_recovers_eod_rows_from_partition_date_when_index_ts_is_null(tmp_path):
    store = ComputedTimeseriesStore(base_dir=tmp_path)
    symbol = "IRS::TEST_LEGACY_NULL_INDEX"
    trading_date = datetime.date(2025, 1, 6)
    part_dir = tmp_path / "asset=IRS__TEST_LEGACY_NULL_INDEX" / "date=2025-01-06"
    part_dir.mkdir(parents=True, exist_ok=True)

    table = pa.table(
        {
            "_index_ts": pa.array([None], type=pa.timestamp("us")),
            "value": pa.array([0.051], type=pa.float64()),
            "_column_name": pa.array(["USD-SOFR-1D 1Y1Y OUTRIGHT RATE"], type=pa.string()),
        }
    )
    pq.write_table(table, part_dir / "legacy-null-index.parquet")

    rows = store.read_rows(
        symbol=symbol,
        reference_points=[trading_date],
        intraday=False,
        skip_current_eod=False,
        fallback_column_name="fallback",
    )

    assert rows == [
        (trading_date, "USD-SOFR-1D 1Y1Y OUTRIGHT RATE", 0.051),
    ]


def test_irswaps_tb_uses_shared_computed_store_across_instances(monkeypatch, tmp_path):
    import TB.IRSwapsTB as irs_tb_module

    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y", value=IRSwapValue.RATE)

    monkeypatch.setattr(
        irs_tb_module,
        "_build_row_for_query",
        lambda curve, q, ref_dt, date_col: (ref_dt, q.col_name(q.curve), 0.05 if ref_dt == ts1 else 0.051),
    )

    source = f"TEST_IRS_{uuid.uuid4().hex}"
    mdp1 = _FakeIRSwapsMDP(source=source)
    tb1 = IRSwapsTB(mdp1, show_tqdm=False, ts_base_dir=str(tmp_path))
    out1 = tb1.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2])

    assert mdp1.bulk_calls == 1
    assert list(out1.iloc[:, 0]) == [0.05, 0.051]

    mdp2 = _FakeIRSwapsMDP(source=source)
    tb2 = IRSwapsTB(mdp2, show_tqdm=False, ts_base_dir=str(tmp_path))
    out2 = tb2.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2])

    assert mdp2.bulk_calls == 0
    pd.testing.assert_frame_equal(out1, out2)


def test_fixedratebonds_tb_uses_shared_computed_store_across_instances(monkeypatch, tmp_path):
    import TB.FixedRateBondsTB as frb_tb_module

    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)
    q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)

    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (ref_dt, q.col_name(), 4.25 if ref_dt == ts1 else 4.30),
    )

    source = f"TEST_FRB_{uuid.uuid4().hex}"
    mdp1 = _FakeFixedRateBondsMDP(source=source)
    tb1 = FixedRateBondsTB(mdp1, show_tqdm=False, ts_base_dir=str(tmp_path))
    out1 = tb1.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2])

    assert mdp1.bulk_calls == 1
    assert list(out1.iloc[:, 0]) == [4.25, 4.30]

    mdp2 = _FakeFixedRateBondsMDP(source=source)
    tb2 = FixedRateBondsTB(mdp2, show_tqdm=False, ts_base_dir=str(tmp_path))
    out2 = tb2.get_timeseries(start=ts1, end=ts2, queries=[q], timestamps=[ts1, ts2])

    assert mdp2.bulk_calls == 0
    pd.testing.assert_frame_equal(out1, out2)


def test_fixedratebonds_tb_suppresses_row_cache_l2_reads_for_large_daily_scans(monkeypatch, tmp_path):
    import TB.FixedRateBondsTB as frb_tb_module

    q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)
    source = f"TEST_FRB_L2_{uuid.uuid4().hex}"
    mdp = _FakeFixedRateBondsMDP(source=source)
    tb = FixedRateBondsTB(mdp, show_tqdm=False, use_ts_cache=False, ts_base_dir=str(tmp_path))

    probe_cache = _ProbeRecordingCache()
    setattr(tb, tb._cache_attr, probe_cache)

    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (ref_dt, q.col_name(), 4.25),
    )

    start = datetime.date(2025, 1, 1)
    end = datetime.date(2025, 4, 30)
    out = tb.get_timeseries(start=start, end=end, queries=[q], n_jobs=1)

    assert not out.empty
    assert mdp.bulk_calls == 1
    assert probe_cache.contains_flags
    assert all(flag is False for flag in probe_cache.contains_flags)
    assert probe_cache._l2_read is True


def test_fixedratebonds_tb_skips_known_bad_fedinvest_rl_daily_dates(monkeypatch, tmp_path):
    import TB.FixedRateBondsTB as frb_tb_module

    q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)
    mdp = _FakeFixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
    tb = FixedRateBondsTB(mdp, show_tqdm=False, use_ts_cache=False, ts_base_dir=str(tmp_path))

    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (ref_dt, q.col_name(), float(ref_dt.day)),
    )

    out = tb.get_timeseries(
        start=datetime.date(2014, 9, 11),
        end=datetime.date(2014, 9, 15),
        queries=[q],
        ignore_cache=True,
        n_jobs=1,
    )

    assert mdp.bulk_calls == 1
    assert mdp.bulk_timestamps == [[datetime.date(2014, 9, 11), datetime.date(2014, 9, 15)]]
    assert list(out.index) == [datetime.date(2014, 9, 11), datetime.date(2014, 9, 15)]


def test_fixedratebonds_tb_skips_known_bad_fedinvest_rl_intraday_timestamps(monkeypatch, tmp_path):
    import TB.FixedRateBondsTB as frb_tb_module

    bad_ts = datetime.datetime(2014, 11, 21, 14, 0, tzinfo=datetime.timezone.utc)
    good_ts = datetime.datetime(2014, 11, 24, 14, 0, tzinfo=datetime.timezone.utc)
    q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)
    mdp = _FakeFixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
    tb = FixedRateBondsTB(mdp, show_tqdm=False, use_ts_cache=False, ts_base_dir=str(tmp_path))

    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (ref_dt, q.col_name(), 4.25),
    )

    out = tb.get_timeseries(
        start=bad_ts,
        end=good_ts,
        queries=[q],
        timestamps=[bad_ts, good_ts],
        freq="1H",
        ignore_cache=True,
        n_jobs=1,
    )

    assert mdp.bulk_calls == 1
    assert mdp.bulk_timestamps == [[good_ts]]
    assert list(out.index) == [good_ts]


def test_fixedratebonds_build_row_fast_paths_simple_ytm_queries(monkeypatch):
    import TB.FixedRateBondsTB as frb_tb_module

    q = FixedRateBondQuery(cusip="CT10", value=FixedRateBondValue.YTM)

    monkeypatch.setattr(
        frb_tb_module,
        "resolve_query",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("resolve_query should not run for simple YTM")),
    )

    row = frb_tb_module._build_row_for_query(
        {"CT10": _YTMPricer(4.125)},
        q,
        datetime.date(2025, 1, 6),
        "Date",
    )

    assert row == (datetime.date(2025, 1, 6), q.col_name(), 4.125)


def test_fixedratebonds_tb_assembles_curve_ytm_from_cached_legs(monkeypatch, tmp_path):
    """When individual outright leg YTMs are cached, a CURVE YTM composite
    should be assembled arithmetically (back - front) without calling MDP."""
    import TB.FixedRateBondsTB as frb_tb_module

    source = f"TEST_FRB_LEG_CURVE_{uuid.uuid4().hex}"
    mdp = _FakeFixedRateBondsMDP(source=source)
    tb = FixedRateBondsTB(mdp, show_tqdm=False, ts_base_dir=str(tmp_path))

    d1 = datetime.date(2024, 6, 3)
    d2 = datetime.date(2024, 6, 4)

    q_ct5 = FixedRateBondQuery(cusip="CT5", value=FixedRateBondValue.YTM)
    q_ct30 = FixedRateBondQuery(cusip="CT30", value=FixedRateBondValue.YTM)

    sym_ct5 = tb._ts_symbol_for_query(q_ct5)
    sym_ct30 = tb._ts_symbol_for_query(q_ct30)

    tb._computed_ts_store.append_many_rows(rows_by_symbol={
        sym_ct5: [
            (d1, q_ct5.col_name(), 4.25),
            (d2, q_ct5.col_name(), 4.30),
        ],
        sym_ct30: [
            (d1, q_ct30.col_name(), 4.75),
            (d2, q_ct30.col_name(), 4.80),
        ],
    })

    q_curve = FixedRateBondQuery(cusip="CT5/CT30", value=FixedRateBondValue.YTM)

    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (_ for _ in ()).throw(
            AssertionError("_build_row_for_query should not be called — legs are cached")
        ),
    )

    out = tb.get_timeseries(start=d1, end=d2, queries=[q_curve], n_jobs=1)

    assert mdp.bulk_calls == 0, "MDP should not have been called"
    assert list(out.index) == [d1, d2]
    col = q_curve.col_name()
    assert abs(out.loc[d1, col] - 0.50) < 1e-10  # 4.75 - 4.25
    assert abs(out.loc[d2, col] - 0.50) < 1e-10  # 4.80 - 4.30


def test_fixedratebonds_tb_assembles_fly_ytm_from_cached_legs(monkeypatch, tmp_path):
    """FLY YTM = 2*belly - front - back, assembled from cached outright legs."""
    import TB.FixedRateBondsTB as frb_tb_module

    source = f"TEST_FRB_LEG_FLY_{uuid.uuid4().hex}"
    mdp = _FakeFixedRateBondsMDP(source=source)
    tb = FixedRateBondsTB(mdp, show_tqdm=False, ts_base_dir=str(tmp_path))

    d1 = datetime.date(2024, 6, 3)

    q_ct5 = FixedRateBondQuery(cusip="CT5", value=FixedRateBondValue.YTM)
    q_ct7 = FixedRateBondQuery(cusip="CT7", value=FixedRateBondValue.YTM)
    q_ct30 = FixedRateBondQuery(cusip="CT30", value=FixedRateBondValue.YTM)

    tb._computed_ts_store.append_many_rows(rows_by_symbol={
        tb._ts_symbol_for_query(q_ct5): [(d1, q_ct5.col_name(), 4.25)],
        tb._ts_symbol_for_query(q_ct7): [(d1, q_ct7.col_name(), 4.40)],
        tb._ts_symbol_for_query(q_ct30): [(d1, q_ct30.col_name(), 4.75)],
    })

    q_fly = FixedRateBondQuery(cusip="CT5/CT7/CT30", value=FixedRateBondValue.YTM)

    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (_ for _ in ()).throw(
            AssertionError("_build_row_for_query should not be called — legs are cached")
        ),
    )

    out = tb.get_timeseries(start=d1, end=d1, queries=[q_fly], n_jobs=1)

    assert mdp.bulk_calls == 0
    col = q_fly.col_name()
    expected = 2 * 4.40 - 4.25 - 4.75  # -0.20
    assert abs(out.loc[d1, col] - expected) < 1e-10


def test_fixedratebonds_tb_leg_assembly_partial_coverage_falls_through(monkeypatch, tmp_path):
    """When only some legs are cached, uncovered dates fall through to MDP pricing."""
    import TB.FixedRateBondsTB as frb_tb_module

    source = f"TEST_FRB_LEG_PARTIAL_{uuid.uuid4().hex}"
    mdp = _FakeFixedRateBondsMDP(source=source)
    tb = FixedRateBondsTB(mdp, show_tqdm=False, ts_base_dir=str(tmp_path))

    d1 = datetime.date(2024, 6, 3)
    d2 = datetime.date(2024, 6, 4)

    q_ct5 = FixedRateBondQuery(cusip="CT5", value=FixedRateBondValue.YTM)
    q_ct30 = FixedRateBondQuery(cusip="CT30", value=FixedRateBondValue.YTM)

    # Only cache CT5 for d1 and d2, but CT30 only for d1
    tb._computed_ts_store.append_many_rows(rows_by_symbol={
        tb._ts_symbol_for_query(q_ct5): [
            (d1, q_ct5.col_name(), 4.25),
            (d2, q_ct5.col_name(), 4.30),
        ],
        tb._ts_symbol_for_query(q_ct30): [
            (d1, q_ct30.col_name(), 4.75),
        ],
    })

    q_curve = FixedRateBondQuery(cusip="CT5/CT30", value=FixedRateBondValue.YTM)

    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (ref_dt, q.col_name(), 0.55),
    )

    out = tb.get_timeseries(start=d1, end=d2, queries=[q_curve], n_jobs=1)

    # d1 assembled from legs, d2 falls through to MDP
    assert mdp.bulk_calls == 1
    col = q_curve.col_name()
    assert abs(out.loc[d1, col] - 0.50) < 1e-10  # assembled: 4.75 - 4.25
    assert abs(out.loc[d2, col] - 0.55) < 1e-10  # from _build_row_for_query mock


def test_fixedratebonds_tb_leg_assembly_skips_custom_risk_weights(monkeypatch, tmp_path):
    """Composites with custom structure_kwargs bypass leg assembly."""
    import TB.FixedRateBondsTB as frb_tb_module

    source = f"TEST_FRB_LEG_CUSTOM_{uuid.uuid4().hex}"
    mdp = _FakeFixedRateBondsMDP(source=source)
    tb = FixedRateBondsTB(mdp, show_tqdm=False, ts_base_dir=str(tmp_path))

    d1 = datetime.date(2024, 6, 3)

    q_ct5 = FixedRateBondQuery(cusip="CT5", value=FixedRateBondValue.YTM)
    q_ct30 = FixedRateBondQuery(cusip="CT30", value=FixedRateBondValue.YTM)

    tb._computed_ts_store.append_many_rows(rows_by_symbol={
        tb._ts_symbol_for_query(q_ct5): [(d1, q_ct5.col_name(), 4.25)],
        tb._ts_symbol_for_query(q_ct30): [(d1, q_ct30.col_name(), 4.75)],
    })

    # Custom risk_weights — should NOT use leg assembly
    q_custom = FixedRateBondQuery(
        cusip="CT5/CT30",
        value=FixedRateBondValue.YTM,
        structure_kwargs={"risk_weights": [0.5, 0.5]},
    )

    build_row_called = []
    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (
            build_row_called.append(True) or (ref_dt, q.col_name(), 0.99)
        ),
    )

    out = tb.get_timeseries(start=d1, end=d1, queries=[q_custom], n_jobs=1)

    assert mdp.bulk_calls == 1, "MDP should be called — custom risk_weights"
    assert len(build_row_called) == 1


def test_fixedratebonds_tb_skips_composite_when_leg_pricer_missing(monkeypatch, tmp_path):
    """When a leg pricer is missing from bulk_get_data (data gap), the composite
    date should be silently skipped rather than crashing with a KeyError on
    resolved CUSIPs."""
    import TB.FixedRateBondsTB as frb_tb_module
    from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure

    source = f"TEST_FRB_MISSING_LEG_{uuid.uuid4().hex}"

    class _PartialMDP(_FakeFixedRateBondsMDP):
        def bulk_get_data(self, timestamps, cusips, **kw):
            self.bulk_calls += 1
            self.bulk_timestamps.append(list(timestamps))
            result = {}
            for ts in timestamps:
                pricers = {}
                for c in cusips:
                    if c == "CT7":
                        continue  # simulate FedInvest data gap for CT7
                    pricers[c] = _YTMPricer(4.0)
                result[ts] = pricers
            return result

    mdp = _PartialMDP(source=source)
    tb = FixedRateBondsTB(mdp, show_tqdm=False, use_ts_cache=False, ts_base_dir=str(tmp_path))

    d1 = datetime.date(2024, 6, 3)
    q_fly = FixedRateBondQuery(cusip="CT5/CT7/CT30", value=FixedRateBondValue.YTM)

    build_row_called = []
    monkeypatch.setattr(
        frb_tb_module,
        "_build_row_for_query",
        lambda pr_map, q, ref_dt, date_col: (
            build_row_called.append(True) or (ref_dt, q.col_name(), -0.10)
        ),
    )

    out = tb.get_timeseries(start=d1, end=d1, queries=[q_fly], n_jobs=1)

    assert len(build_row_called) == 0, "_build_row_for_query should not be called when a leg is missing"
    assert out.empty or q_fly.col_name() not in out.columns or out[q_fly.col_name()].isna().all()
