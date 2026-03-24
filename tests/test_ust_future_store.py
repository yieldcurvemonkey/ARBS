import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from Caching.supabase_ustf_sync import (
    USTF_BASIS_REPORT_BLOCKS_TABLE,
    USTF_SNAPSHOT_BLOCKS_TABLE,
    SupabaseUSTFutureSync,
)
from Caching.ust_future_store import USTFutureStore


class _Result:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeEngine:
    def __init__(self):
        self.blocks = {}

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, stmt, params=None):
        sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
        params = params or {}

        for table in (USTF_SNAPSHOT_BLOCKS_TABLE, USTF_BASIS_REPORT_BLOCKS_TABLE):
            if f"INSERT INTO {table}" in sql:
                key = (table, params["trading_date"], params["symbol"])
                self.blocks[key] = SimpleNamespace(**params)
                return _Result()
            if f"FROM {table}" in sql and "BETWEEN" in sql:
                rows = [
                    SimpleNamespace(**row.__dict__)
                    for (tbl, _date, _symbol), row in sorted(self.blocks.items(), key=lambda item: item[0][1])
                    if tbl == table and _symbol == params["symbol"] and params["start"] <= _date <= params["end"]
                ]
                return _Result(rows=rows)
            if f"FROM {table}" in sql:
                row = self.blocks.get((table, params["trading_date"], params["symbol"]))
                return _Result(row=row)
        return _Result()


@pytest.fixture
def snapshot_df():
    return pd.DataFrame(
        [
            {
                "symbol": "USM26",
                "timestamp_utc": pd.Timestamp("2026-03-24T19:00:00Z"),
                "trading_date": datetime.date(2026, 3, 24),
                "session_minute": 840,
                "price": 112.25,
            }
        ]
    )


@pytest.fixture
def basis_df():
    return pd.DataFrame(
        [
            {
                "cusip": "1",
                "label": "A",
                "clean_price": 90.0,
                "ytm": 4.9,
                "invoice_cf": 0.8,
                "gross_basis": 0.1,
                "bnoc": 0.05,
                "irr": 5.1,
                "is_ctd": True,
                "symbol": "USM26",
                "timestamp_utc": pd.Timestamp("2026-03-24T19:00:00Z"),
                "trading_date": datetime.date(2026, 3, 24),
                "session_minute": 840,
                "futures_price": 112.25,
                "futures_ytm": 4.95,
                "repo_rate": 4.33,
                "settlement_date": datetime.date(2026, 3, 26),
                "delivery_date": datetime.date(2026, 6, 17),
            }
        ]
    )


def test_snapshot_roundtrip(monkeypatch, tmp_path, snapshot_df):
    monkeypatch.setattr("Caching.ust_future_store._get_ustf_sync", lambda base_dir=None: None)
    store = USTFutureStore(base_dir=tmp_path)

    store.write_snapshot_day("USM26", datetime.date(2026, 3, 24), snapshot_df, overwrite=True)
    loaded = store.read_snapshot_day("USM26", datetime.date(2026, 3, 24))

    assert store.has_snapshot_day("USM26", datetime.date(2026, 3, 24))
    assert not loaded.empty
    assert loaded.iloc[0]["symbol"] == "USM26"
    assert float(loaded.iloc[0]["price"]) == pytest.approx(112.25)


def test_basis_report_roundtrip(monkeypatch, tmp_path, basis_df):
    monkeypatch.setattr("Caching.ust_future_store._get_ustf_sync", lambda base_dir=None: None)
    store = USTFutureStore(base_dir=tmp_path)

    store.write_basis_report_day("USM26", datetime.date(2026, 3, 24), basis_df, overwrite=True)
    loaded = store.read_basis_report_day("USM26", datetime.date(2026, 3, 24))

    assert store.has_basis_report_day("USM26", datetime.date(2026, 3, 24))
    assert not loaded.empty
    assert loaded.iloc[0]["cusip"] == "1"
    assert float(loaded.iloc[0]["bnoc"]) == pytest.approx(0.05)


def test_supabase_sync_push_pull_and_prefetch(monkeypatch, tmp_path, snapshot_df, basis_df):
    monkeypatch.setattr("Caching.ust_future_store._get_ustf_sync", lambda base_dir=None: None)
    monkeypatch.setattr("Caching.supabase_schema.ensure_schema", lambda engine=None: True)
    engine = _FakeEngine()

    producer = USTFutureStore(base_dir=tmp_path / "producer")
    consumer = USTFutureStore(base_dir=tmp_path / "consumer")

    producer.write_snapshot_day("USM26", datetime.date(2026, 3, 24), snapshot_df, overwrite=True)
    producer.write_basis_report_day("USM26", datetime.date(2026, 3, 24), basis_df, overwrite=True)
    producer.write_snapshot_day("USM26", datetime.date(2026, 3, 25), snapshot_df.assign(trading_date=datetime.date(2026, 3, 25)), overwrite=True)
    producer.write_basis_report_day("USM26", datetime.date(2026, 3, 25), basis_df.assign(trading_date=datetime.date(2026, 3, 25)), overwrite=True)

    producer_sync = SupabaseUSTFutureSync(base_dir=producer.base_dir, engine=engine)
    consumer_sync = SupabaseUSTFutureSync(base_dir=consumer.base_dir, engine=engine)

    assert producer_sync.push_snapshot_day("USM26", datetime.date(2026, 3, 24)) is True
    assert producer_sync.push_basis_report_day("USM26", datetime.date(2026, 3, 24)) is True
    assert producer_sync.push_snapshot_day("USM26", datetime.date(2026, 3, 25)) is True
    assert producer_sync.push_basis_report_day("USM26", datetime.date(2026, 3, 25)) is True

    assert consumer_sync.pull_snapshot_day("USM26", datetime.date(2026, 3, 24)) is True
    assert consumer_sync.pull_basis_report_day("USM26", datetime.date(2026, 3, 24)) is True
    assert not consumer.read_snapshot_day("USM26", datetime.date(2026, 3, 24)).empty
    assert not consumer.read_basis_report_day("USM26", datetime.date(2026, 3, 24)).empty

    fetched_snapshots = consumer_sync.prefetch_snapshot_range("USM26", datetime.date(2026, 3, 24), datetime.date(2026, 3, 25))
    fetched_reports = consumer_sync.prefetch_basis_report_range("USM26", datetime.date(2026, 3, 24), datetime.date(2026, 3, 25))

    assert datetime.date(2026, 3, 25) in fetched_snapshots
    assert datetime.date(2026, 3, 25) in fetched_reports
