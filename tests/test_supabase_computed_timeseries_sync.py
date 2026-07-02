import datetime
import io
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow.parquet as pq

from Caching.computed_timeseries_store import ComputedTimeseriesStore
from Caching.supabase_computed_timeseries_sync import (
    COMPUTED_TIMESERIES_BLOCKS_TABLE,
    SupabaseComputedTimeseriesSync,
)
from Caching.timeseries_cache import append_timeseries


class _FakeResult:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeEngine:
    def __init__(self):
        self.blob_store: dict[tuple[str, datetime.date], dict] = {}

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, stmt, params=None):
        sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
        params = params or {}

        if "CREATE TABLE" in sql or "CREATE INDEX" in sql:
            return _FakeResult()

        if f"INSERT INTO {COMPUTED_TIMESERIES_BLOCKS_TABLE}" in sql:
            key = (params["symbol"], params["trading_date"])
            self.blob_store[key] = dict(params)
            return _FakeResult()

        if (
            f"FROM {COMPUTED_TIMESERIES_BLOCKS_TABLE}" in sql
            and "payload, sha256, data_format" in sql
        ):
            key = (params["symbol"], params["trading_date"])
            payload = self.blob_store.get(key)
            if payload is None:
                return _FakeResult(row=None)
            return _FakeResult(
                row=SimpleNamespace(
                    payload=payload["payload"],
                    sha256=payload["sha256"],
                    data_format=payload["data_format"],
                )
            )

        if (
            f"FROM {COMPUTED_TIMESERIES_BLOCKS_TABLE}" in sql
            and "trading_date, payload, sha256" in sql
        ):
            rows = [
                SimpleNamespace(
                    trading_date=trading_date,
                    payload=payload["payload"],
                    sha256=payload["sha256"],
                )
                for (symbol, trading_date), payload in sorted(self.blob_store.items(), key=lambda item: item[0][1])
                if symbol == params["symbol"] and params["start"] <= trading_date <= params["end"]
            ]
            return _FakeResult(rows=rows)

        return _FakeResult()


class _ImmediateThread:
    def __init__(self, *, target, daemon=False, name=None):
        self._target = target
        self._daemon = daemon
        self._name = name

    def start(self):
        self._target()


def test_supabase_computed_timeseries_sync_push_and_pull_roundtrip(tmp_path):
    engine = _FakeEngine()
    symbol = "IRS::USD-SOFR-1D::5Y::RATE"
    trading_date = datetime.date(2025, 1, 6)
    idx = [
        datetime.datetime(2025, 1, 6, 14, 0),
        datetime.datetime(2025, 1, 6, 15, 0),
    ]
    append_timeseries(
        None,
        symbol,
        df=pd.DataFrame(
            {"value": [0.051, 0.052], "_column_name": ["col", "col"]},
            index=pd.DatetimeIndex(idx),
        ),
        opts=ComputedTimeseriesStore(base_dir=tmp_path / "producer").write_options,
    )

    producer_sync = SupabaseComputedTimeseriesSync(base_dir=tmp_path / "producer", engine=engine)
    assert producer_sync.push_day(symbol, trading_date) is True
    assert (symbol, trading_date) in engine.blob_store

    payload = engine.blob_store[(symbol, trading_date)]["payload"]
    table = pq.read_table(io.BytesIO(payload))
    assert table.num_rows == 2

    consumer_sync = SupabaseComputedTimeseriesSync(base_dir=tmp_path / "consumer", engine=engine)
    assert consumer_sync.pull_day(symbol, trading_date) is True

    part_dir = tmp_path / "consumer" / "asset=IRS__USD-SOFR-1D__5Y__RATE" / "date=2025-01-06"
    assert part_dir.exists()
    assert len(list(part_dir.glob("*.parquet"))) == 1


def test_computed_timeseries_store_reads_from_supabase_l2_when_local_cache_is_empty(tmp_path, monkeypatch):
    import Caching.computed_timeseries_store as store_mod

    engine = _FakeEngine()
    symbol = "IRS::USD-SOFR-1D::5Y::RATE"
    ts1 = datetime.datetime(2025, 1, 6, 14, 0, tzinfo=datetime.timezone.utc)
    ts2 = datetime.datetime(2025, 1, 6, 15, 0, tzinfo=datetime.timezone.utc)

    def _sync_for(base_dir):
        return SupabaseComputedTimeseriesSync(base_dir=Path(base_dir), engine=engine)

    monkeypatch.setattr(store_mod, "_get_computed_ts_sync", _sync_for)
    monkeypatch.setattr(store_mod.threading, "Thread", _ImmediateThread)

    producer_store = ComputedTimeseriesStore(base_dir=tmp_path / "producer")
    producer_store.append_rows(
        symbol=symbol,
        rows=[
            (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
            (ts2, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.052),
        ],
    )

    assert (symbol, datetime.date(2025, 1, 6)) in engine.blob_store

    consumer_store = ComputedTimeseriesStore(base_dir=tmp_path / "consumer")
    rows = consumer_store.read_rows(
        symbol=symbol,
        reference_points=[ts1, ts2],
        intraday=True,
        skip_current_eod=False,
        fallback_column_name="fallback",
    )

    assert rows == [
        (ts1, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.051),
        (ts2, "USD-SOFR-1D 5Y OUTRIGHT RATE", 0.052),
    ]
