from __future__ import annotations

import datetime as dt
import json
import sys

import scripts.tape_v3_backfill as tape_v3_backfill
from scripts.tape_v3_backfill import load_ledger


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


def _install_fake_db(monkeypatch, days: list[dt.date], row_counts: dict[str, int] | None = None):
    """Mock the database entirely -- no connection is ever made.

    `days` stands in for the ground-truth day set that would otherwise
    come from `SELECT DISTINCT as_of_date FROM arbs_usd_swap_tape_legs_v2
    ...`. `row_counts` stands in for the per-day
    `SELECT count(*) FROM arbs_usd_swap_tape_legs_v3 WHERE as_of_date = :d`
    check; any date not given an explicit entry defaults to a nonzero
    row count so tests that aren't specifically about the zero-row rule
    keep their old "returncode 0 => ok" behaviour.

    `raising=False` on every setattr is deliberate: these attributes do
    not exist on the pre-fix module at all, and this helper is used both
    to observe the pre-fix failures and to drive the post-fix tests.
    """
    row_counts = row_counts or {}
    monkeypatch.setattr(tape_v3_backfill, "_engine", lambda: None, raising=False)
    monkeypatch.setattr(
        tape_v3_backfill, "target_days",
        lambda engine, start, end: list(days), raising=False,
    )
    monkeypatch.setattr(
        tape_v3_backfill, "v3_row_count",
        lambda engine, d: row_counts.get(d.isoformat(), 1), raising=False,
    )


def test_main_resume_runs_only_non_ok_days(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    _write_ledger(ledger, [
        {"date": "2026-08-07", "status": "ok"},
        {"date": "2026-08-06", "status": "failed"},
        # 2026-08-05, 2026-08-04, 2026-08-03: never attempted
    ])
    calls: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, calls, returncode=0)
    _install_fake_db(monkeypatch, days=[
        dt.date(2026, 8, 7), dt.date(2026, 8, 6), dt.date(2026, 8, 5),
        dt.date(2026, 8, 4), dt.date(2026, 8, 3),
    ])
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
    _install_fake_db(monkeypatch, days=[
        dt.date(2026, 8, 7), dt.date(2026, 8, 6), dt.date(2026, 8, 5),
        dt.date(2026, 8, 4), dt.date(2026, 8, 3),
    ])
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
    _install_fake_db(monkeypatch, days=[
        dt.date(2026, 8, 7), dt.date(2026, 8, 6), dt.date(2026, 8, 5),
        dt.date(2026, 8, 4), dt.date(2026, 8, 3),
    ])
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


def test_main_records_failed_when_subprocess_ok_but_zero_rows(tmp_path, monkeypatch):
    """C1: a day the pipeline exits 0 for but writes zero rows must NOT be
    recorded ok. DTCC 503s get swallowed by the fetcher into an empty
    frame, and the pipeline legitimately writes nothing and stamps its
    own run 'success' regardless -- exactly what happened to six live
    days (2026-07-22, 07-23, 07-24, 07-27, 07-28, 07-29), each recorded
    `ok` with zero rows in v3 against thousands of rows in v2. Because
    --retry-failed only ever selects status == "failed", an `ok` record
    like that is permanently unrepairable.
    """
    ledger = tmp_path / "ledger.jsonl"
    calls: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, calls, returncode=0)
    _install_fake_db(
        monkeypatch,
        days=[dt.date(2026, 7, 23)],
        row_counts={"2026-07-23": 0},
    )
    monkeypatch.setattr(sys, "argv", [
        "tape_v3_backfill.py",
        "--start", "2026-07-23", "--end", "2026-07-23",
        "--ledger", str(ledger),
    ])

    rc = tape_v3_backfill.main()

    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["status"] == "failed"
    assert records[0]["returncode"] == 0
    assert records[0].get("rows") == 0
    assert rc == 1


def test_main_records_ok_when_subprocess_ok_and_rows_present(tmp_path, monkeypatch):
    """A day that exits 0 and actually wrote rows is still recorded ok --
    the row-count check must not turn every day into a false failure."""
    ledger = tmp_path / "ledger.jsonl"
    calls: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, calls, returncode=0)
    _install_fake_db(
        monkeypatch,
        days=[dt.date(2026, 7, 21)],
        row_counts={"2026-07-21": 4200},
    )
    monkeypatch.setattr(sys, "argv", [
        "tape_v3_backfill.py",
        "--start", "2026-07-21", "--end", "2026-07-21",
        "--ledger", str(ledger),
    ])

    rc = tape_v3_backfill.main()

    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["status"] == "ok"
    assert records[0]["rows"] == 4200
    assert rc == 0


def test_main_day_list_comes_from_database_not_holiday_calendar(tmp_path, monkeypatch):
    """I2: 2024-10-14 is Columbus Day, a US federal holiday, so the old
    USFederalHolidayCalendar-derived day list wrongly excludes it even
    though v2 has real data for it. The runner must process it because
    the day list now comes from the database, not the calendar.
    """
    ledger = tmp_path / "ledger.jsonl"
    calls: list[list[str]] = []
    _install_fake_subprocess(monkeypatch, calls, returncode=0)
    _install_fake_db(
        monkeypatch,
        days=[dt.date(2024, 10, 14)],
        row_counts={"2024-10-14": 3},
    )
    monkeypatch.setattr(sys, "argv", [
        "tape_v3_backfill.py",
        "--start", "2024-10-14", "--end", "2024-10-14",
        "--ledger", str(ledger),
    ])

    tape_v3_backfill.main()

    assert _run_dates(calls) == {"2024-10-14"}
