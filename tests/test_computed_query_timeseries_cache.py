import datetime
import uuid
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
        return {ts: {cusip: {"cusip": cusip, "timestamp": ts} for cusip in cusips} for ts in timestamps}


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
