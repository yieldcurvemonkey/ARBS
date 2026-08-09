from __future__ import annotations

import datetime as dt
import json
import sys

import scripts.tape_v3_backfill as tape_v3_backfill
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


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


def _write_ledger(path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _run_dates(calls: list[list[str]]) -> set[str]:
    dates = set()
    for cmd in calls:
        dates.add(cmd[cmd.index("--date") + 1])
    return dates


def _install_fake_subprocess(monkeypatch, calls: list[list[str]], returncode: int = 0):
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompletedProcess(returncode=returncode)

    monkeypatch.setattr(tape_v3_backfill.subprocess, "run", fake_run)


def test_main_resume_runs_only_non_ok_days(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        {"date": "2026-08-07", "status": "ok"},
        {"date": "2026-08-06", "status": "failed"},
        # 2026-08-05, 2026-08-04, 2026-08-03: never attempted
    ])
    calls: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, calls, returncode=0)
    monkeypatch.setattr(sys, "argv", [
        "tape_v3_backfill.py",
        "--start", "2026-08-03", "--end", "2026-08-07",
        "--ledger", str(ledger),
    ])

    tape_v3_backfill.main()

    assert _run_dates(calls) == {
        "2026-08-06", "2026-08-05", "2026-08-04", "2026-08-03",
    }


def test_main_retry_failed_runs_only_failed_days(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        {"date": "2026-08-07", "status": "ok"},
        {"date": "2026-08-06", "status": "failed"},
        # 2026-08-05, 2026-08-04, 2026-08-03: never attempted
    ])
    calls: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, calls, returncode=0)
    monkeypatch.setattr(sys, "argv", [
        "tape_v3_backfill.py",
        "--start", "2026-08-03", "--end", "2026-08-07",
        "--ledger", str(ledger),
        "--retry-failed",
    ])

    tape_v3_backfill.main()

    assert _run_dates(calls) == {"2026-08-06"}


def test_main_exit_code_reflects_never_attempted_days_after_retry(tmp_path, monkeypatch):
    """Regression test: a day with NO ledger entry (process killed mid-run,
    before that day was ever attempted) must still force a nonzero exit,
    even after --retry-failed cleans up every day that IS marked failed.
    """
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        {"date": "2026-08-07", "status": "ok"},
        {"date": "2026-08-06", "status": "failed"},
        # 2026-08-05, 2026-08-04, 2026-08-03: never attempted
    ])
    calls: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, calls, returncode=0)
    monkeypatch.setattr(sys, "argv", [
        "tape_v3_backfill.py",
        "--start", "2026-08-03", "--end", "2026-08-07",
        "--ledger", str(ledger),
        "--retry-failed",
    ])

    rc = tape_v3_backfill.main()

    # --retry-failed only reruns 2026-08-06 (now "ok"). 2026-08-05/04/03
    # were never attempted and remain absent from the ledger, so the run
    # is NOT complete: exit code must be 1, not 0.
    assert rc == 1
