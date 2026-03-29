import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from Caching.supabase_forex_factory_calendar_sync import SupabaseForexFactoryCalendarSync
from RVUtils.forex_factory_calendar import ForexFactoryCalendarFetcher


def _calendar_day_frame(trading_date: dt.date, event_id: int, title: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "EventId": event_id,
                "WeekAnchor": trading_date - dt.timedelta(days=trading_date.weekday()),
                "Date": trading_date,
                "TimeLabel": "8:30am",
                "Timestamp": pd.Timestamp(dt.datetime.combine(trading_date, dt.time(13, 30), tzinfo=dt.timezone.utc)),
                "CalendarTimeZone": "America/New_York",
                "Currency": "USD",
                "Impact": "high",
                "ImpactRank": 3,
                "Title": title,
                "DetailLevel": 2,
                "Actual": "1.0%",
                "Forecast": "0.9%",
                "Previous": "0.8%",
                "ActualOutcome": "better",
                "PreviousRevised": False,
                "PreviousRevisionDirection": None,
                "SourceURL": "https://www.forexfactory.com/calendar",
            }
        ]
    )


class _FakeEngine:
    def __init__(self) -> None:
        self.store: dict[dt.date, dict] = {}

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, stmt, params=None):
        sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
        params = params or {}
        if "INSERT INTO arbs_forex_factory_calendar_blocks_v1" in sql:
            self.store[params["trading_date"]] = dict(params)
            return MagicMock()
        if "SELECT payload, sha256, data_format" in sql:
            row = self.store.get(params["trading_date"])
            result = MagicMock()
            result.fetchone.return_value = SimpleNamespace(**row) if row else None
            return result
        if "SELECT trading_date, payload, sha256" in sql:
            rows = [
                SimpleNamespace(trading_date=trading_date, payload=row["payload"], sha256=row["sha256"])
                for trading_date, row in sorted(self.store.items())
                if params["start"] <= trading_date <= params["end"]
            ]
            result = MagicMock()
            result.fetchall.return_value = rows
            return result
        return MagicMock()


def test_supabase_calendar_sync_push_and_pull_roundtrip(tmp_path):
    producer_dir = tmp_path / "producer"
    consumer_dir = tmp_path / "consumer"
    trading_date = dt.date(2026, 3, 6)

    producer_fetcher = ForexFactoryCalendarFetcher(core_base_dir=producer_dir)
    producer_fetcher.write_day(trading_date, _calendar_day_frame(trading_date, 1, "Non-Farm Employment Change"))

    fake_engine = _FakeEngine()
    producer_sync = SupabaseForexFactoryCalendarSync(base_dir=producer_dir, engine=fake_engine)
    consumer_sync = SupabaseForexFactoryCalendarSync(base_dir=consumer_dir, engine=fake_engine)

    with patch("Caching.supabase_schema.ensure_schema", return_value=True):
        assert producer_sync.push_day(trading_date) is True
        assert consumer_sync.pull_day(trading_date) is True

    consumer_fetcher = ForexFactoryCalendarFetcher(core_base_dir=consumer_dir)
    frame = consumer_fetcher.read_day(trading_date)
    assert frame["Title"].tolist() == ["Non-Farm Employment Change"]
    assert frame["Actual"].tolist() == ["1.0%"]


def test_supabase_calendar_sync_prefetch_range_downloads_missing_days(tmp_path):
    producer_dir = tmp_path / "producer"
    consumer_dir = tmp_path / "consumer"
    fake_engine = _FakeEngine()

    d1 = dt.date(2026, 3, 6)
    d2 = dt.date(2026, 3, 12)
    producer_fetcher = ForexFactoryCalendarFetcher(core_base_dir=producer_dir)
    producer_fetcher.write_day(d1, _calendar_day_frame(d1, 1, "Non-Farm Employment Change"))
    producer_fetcher.write_day(d2, _calendar_day_frame(d2, 2, "CPI m/m"))

    producer_sync = SupabaseForexFactoryCalendarSync(base_dir=producer_dir, engine=fake_engine)
    consumer_sync = SupabaseForexFactoryCalendarSync(base_dir=consumer_dir, engine=fake_engine)

    with patch("Caching.supabase_schema.ensure_schema", return_value=True):
        assert producer_sync.push_day(d1) is True
        assert producer_sync.push_day(d2) is True
        fetched = consumer_sync.prefetch_range(d1, d2)

    assert fetched == [d1, d2]
    assert list((consumer_dir / "date=2026-03-06").glob("*.parquet"))
    assert list((consumer_dir / "date=2026-03-12").glob("*.parquet"))
