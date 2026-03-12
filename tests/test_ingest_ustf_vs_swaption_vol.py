import argparse
import datetime as dt

from SDRUtils._swappulse_scripts import ingest_ustf_vs_swaption_vol as ingest_mod


def test_main_range_continues_when_single_day_fails(monkeypatch):
    called_dates: list[dt.date] = []
    logged_messages: list[tuple[str, str]] = []

    def _stub_create_db_engine():
        return object()

    def _stub_ensure_schema(engine):
        assert engine is not None

    def _stub_run_daily_ingest(engine, *, as_of_date, curve_name, force_refresh):
        assert engine is not None
        assert curve_name == "USD-SOFR-1D"
        assert force_refresh is False
        called_dates.append(as_of_date)
        if as_of_date == dt.date(2026, 3, 4):
            raise RuntimeError("boom")
        return {
            "as_of_date": as_of_date.isoformat(),
            "ustf_rows": 1,
            "swaption_rows": 1,
            "comparison_rows": 1,
        }

    def _stub_log_status(message, *, level="INFO"):
        logged_messages.append((level, message))

    monkeypatch.setattr(ingest_mod, "create_db_engine", _stub_create_db_engine)
    monkeypatch.setattr(ingest_mod, "ensure_schema", _stub_ensure_schema)
    monkeypatch.setattr(ingest_mod, "run_daily_ingest", _stub_run_daily_ingest)
    monkeypatch.setattr(ingest_mod, "_log_status", _stub_log_status)

    args = argparse.Namespace(
        start_date="2026-03-03",
        end_date="2026-03-05",
        curve_name="USD-SOFR-1D",
        lookback_business_days=10,
        force_refresh=False,
    )

    ingest_mod.main_range(args)

    assert called_dates == [
        dt.date(2026, 3, 3),
        dt.date(2026, 3, 4),
        dt.date(2026, 3, 5),
    ]
    assert ("WARN", "Failed backfill dates: 2026-03-04") in logged_messages
    assert (
        "INFO",
        "USTF-vs-swaption backfill complete: success=2 failure=1",
    ) in logged_messages
