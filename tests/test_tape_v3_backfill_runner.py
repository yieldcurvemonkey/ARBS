from __future__ import annotations

import datetime as dt
import json

from scripts.tape_v3_backfill import load_ledger, trading_days


def test_trading_days_are_descending_and_exclude_weekends():
    days = trading_days(dt.date(2026, 8, 3), dt.date(2026, 8, 7))
    assert days == [
        dt.date(2026, 8, 7), dt.date(2026, 8, 6), dt.date(2026, 8, 5),
        dt.date(2026, 8, 4), dt.date(2026, 8, 3),
    ]


def test_trading_days_skips_a_weekend():
    days = trading_days(dt.date(2026, 8, 7), dt.date(2026, 8, 10))
    assert dt.date(2026, 8, 8) not in days   # Saturday
    assert dt.date(2026, 8, 9) not in days   # Sunday


def test_load_ledger_returns_empty_for_missing_file(tmp_path):
    assert load_ledger(tmp_path / "nope.jsonl") == {}


def test_load_ledger_keeps_the_last_status_per_day(tmp_path):
    fp = tmp_path / "ledger.jsonl"
    fp.write_text(
        json.dumps({"date": "2026-08-07", "status": "failed"}) + "\n"
        + json.dumps({"date": "2026-08-07", "status": "ok"}) + "\n",
        encoding="utf-8",
    )
    assert load_ledger(fp) == {"2026-08-07": "ok"}
