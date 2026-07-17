"""Orchestration-logic tests for the multi-day driver (no DB / no network)."""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import SDRUtils._swappulse_scripts.backfill_stir_direction_range as R


class _DummyConn:
    def close(self):
        pass


def test_run_range_calibrates_once_dispatches_all_and_isolates_errors(monkeypatch):
    calls = {"calib": 0, "classify": []}

    monkeypatch.setattr(R.psycopg2, "connect", lambda url: _DummyConn())
    monkeypatch.setattr(R, "resolve_pg_url", lambda: "dummy")
    monkeypatch.setattr(R, "ensure_schema", lambda conn: None)
    monkeypatch.setattr(R, "write_tick_rows", lambda conn, stats: None)

    def fake_calib(conn, s, e, mode):
        calls["calib"] += 1
        return pd.DataFrame()  # empty stats -> records == []

    monkeypatch.setattr(R, "run_calibration", fake_calib)

    def fake_classify(conn, date, stats, dry_run=False, warm_jobs=8):
        calls["classify"].append(date)
        if date == "2026-07-02":
            raise RuntimeError("boom")
        return [{"dealer_direction": "PAID"}] * 3

    monkeypatch.setattr(R, "run_classification", fake_classify)

    res = R.run_range(
        "2026-07-01", "2026-07-03", day_jobs=2, warm_jobs=4, dry_run=True,
        pg_url="dummy", executor_factory=lambda: ThreadPoolExecutor(max_workers=2),
    )

    # calibration computed exactly once for the whole window
    assert calls["calib"] == 1
    # every day dispatched exactly once
    assert sorted(calls["classify"]) == ["2026-07-01", "2026-07-02", "2026-07-03"]
    # results sorted by date
    assert [r["date"] for r in res] == ["2026-07-01", "2026-07-02", "2026-07-03"]
    # one bad day is isolated, others succeed
    by_date = {r["date"]: r for r in res}
    assert by_date["2026-07-02"]["error"] is not None
    assert "boom" in by_date["2026-07-02"]["error"]
    assert by_date["2026-07-01"]["error"] is None
    assert by_date["2026-07-01"]["n"] == 3
    assert by_date["2026-07-01"]["summary"] == {"PAID": 3}


def test_dates_inclusive_range():
    assert R._dates("2026-07-01", "2026-07-03") == [
        "2026-07-01", "2026-07-02", "2026-07-03",
    ]
