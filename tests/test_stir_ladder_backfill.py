import datetime

import pandas as pd

from SDRUtils._swappulse_scripts import _stir_ladder_schema_v1 as schema


def test_ladder_schema_ddl_columns():
    ddl = "\n".join(schema.DDL_STATEMENTS)
    assert "CREATE TABLE IF NOT EXISTS arbs_stir_ladder_prints_v1" in ddl
    assert "CREATE TABLE IF NOT EXISTS arbs_stir_book_marks_v1" in ddl
    for col in (
        "unit_key", "bucket_space", "bucket_key", "delta_dv01",
        "visibility_timestamp", "p_flip", "direction_confidence",
        "curve_suspect_trade", "is_block", "dv01", "projected_at",
    ):
        assert col in ddl, col
    for col in ("mark_ts", "mark_kind", "npv_usd", "pnl_since_entry_usd", "curve_name"):
        assert col in ddl, col


def test_ladder_ensure_schema_executes_all():
    executed = []

    class FakeCursor:
        def execute(self, sql):
            executed.append(sql)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            executed.append("COMMIT")

    schema.ensure_schema(FakeConn())
    assert executed[-1] == "COMMIT"
    assert len(executed) == len(schema.DDL_STATEMENTS) + 1


def test_write_ladder_rows_upsert_sql():
    from SDRUtils._swappulse_scripts import backfill_stir_ladder as bf
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            captured["committed"] = True

    bf._execute_values = lambda cur, sql, vals: captured.update(sql=sql, n=len(vals))
    bf.write_ladder_rows(FakeConn(), [dict(
        unit_key="T1", bucket_space="MEETING", bucket_key="2026-07-29",
        delta_dv01=-50001.0, as_of_date=datetime.date(2026, 7, 10),
        execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        visibility_timestamp=pd.Timestamp("2026-07-10 19:42:45+00:00"),
        p_flip=0.2, direction_confidence="LOW", curve_suspect_trade=False,
        is_block=False, dv01=50001.0,
    )])
    assert "ON CONFLICT (unit_key, bucket_space, bucket_key) DO UPDATE" in captured["sql"]
    assert captured["n"] == 1 and captured["committed"]


def test_write_mark_rows_upsert_sql():
    from SDRUtils._swappulse_scripts import backfill_stir_ladder as bf
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            captured["committed"] = True

    bf._execute_values = lambda cur, sql, vals: captured.update(sql=sql, n=len(vals))
    bf.write_mark_rows(FakeConn(), [dict(
        unit_key="T1", mark_ts=pd.Timestamp("2026-07-10 21:00:00+00:00"),
        mark_kind="EOD", npv_usd=1.0, pnl_since_entry_usd=0.5, curve_name="C",
    )])
    assert "ON CONFLICT (unit_key, mark_ts) DO UPDATE" in captured["sql"]
    assert captured["n"] == 1


# --------------------------- code vintage stamping ---------------------------
def test_code_vintage_is_a_short_sha_or_unknown():
    from SDRUtils.stir_flow.vintage import UNKNOWN_VINTAGE, code_vintage

    v = code_vintage()
    assert isinstance(v, str) and v
    if v == UNKNOWN_VINTAGE:
        return
    sha = v[:-len("+dirty")] if v.endswith("+dirty") else v
    assert len(sha) == 12 and all(c in "0123456789abcdef" for c in sha), v


def test_code_vintage_is_resolved_once():
    """Cached: a per-row subprocess call would dominate a 6-month backfill."""
    from SDRUtils.stir_flow.vintage import code_vintage

    assert code_vintage() is code_vintage()


def test_ladder_schema_adds_code_vintage_idempotently():
    from SDRUtils._swappulse_scripts import _stir_ladder_schema_v1 as schema

    ddl = "\n".join(schema.DDL_STATEMENTS)
    for table in (schema.LADDER_PRINTS_TABLE, schema.BOOK_MARKS_TABLE):
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS code_vintage TEXT" in ddl


def test_direction_schema_adds_code_vintage_idempotently():
    from SDRUtils._swappulse_scripts import _stir_flow_schema_v1 as schema

    ddl = "\n".join(schema.DDL_STATEMENTS)
    assert (f"ALTER TABLE {schema.DIRECTION_TABLE} "
            "ADD COLUMN IF NOT EXISTS code_vintage TEXT") in ddl


def test_written_columns_carry_code_vintage():
    from SDRUtils._swappulse_scripts import backfill_stir_ladder as bf
    from SDRUtils._swappulse_scripts import backfill_stir_direction as bd
    from SDRUtils.stir_flow.ladder import LADDER_COLUMNS

    assert "code_vintage" in LADDER_COLUMNS
    assert "code_vintage" in bf.MARK_COLUMNS
    assert "code_vintage" in bd.DIRECTION_COLUMNS


# ------------------------------ rewrite deletes ------------------------------
class _RecordingCursor:
    def __init__(self, log):
        self.log = log
        self.rowcount = 7

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _RecordingConn:
    def __init__(self):
        self.log = []
        self.commits = 0

    def cursor(self):
        return _RecordingCursor(self.log)

    def commit(self):
        self.commits += 1


def test_delete_projections_clears_rows_and_entry_marks_only():
    """ENTRY marks must go too: their PK includes mark_ts, so a re-snap would
    otherwise leave the old mark behind as a phantom entry price."""
    from SDRUtils._swappulse_scripts import backfill_stir_ladder as bf

    conn = _RecordingConn()
    n_rows, n_marks = bf.delete_projections(conn, "2026-07-01", "2026-07-31")
    sqls = [s for s, _p in conn.log]
    assert len(sqls) == 2
    assert "mark_kind = 'ENTRY'" in sqls[0] and f"DELETE FROM {bf.BOOK_MARKS_TABLE}" in sqls[0]
    assert "EOD" not in sqls[0]
    assert f"DELETE FROM {bf.LADDER_PRINTS_TABLE}" in sqls[1]
    assert n_rows == 7 and n_marks == 7 and conn.commits == 1


def test_delete_eod_marks_is_scoped_to_eod_and_et_dates():
    from SDRUtils._swappulse_scripts import backfill_stir_ladder as bf

    conn = _RecordingConn()
    assert bf.delete_eod_marks(conn, "2026-07-01", "2026-07-31") == 7
    sql, params = conn.log[0]
    assert "mark_kind = 'EOD'" in sql
    assert "America/New_York" in sql
    assert params == {"s": "2026-07-01", "e": "2026-07-31"}


# ------------------------------ range driver ---------------------------------
def test_run_range_dispatches_business_days_and_isolates_errors(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from SDRUtils._swappulse_scripts import backfill_stir_ladder as bf

    seen = []

    def fake_worker(job):
        date_iso = job[0]
        seen.append(date_iso)
        if date_iso == "2026-07-02":
            return {"date": date_iso, "projected": 0, "eligible": 0, "errors": {},
                    "error": "boom"}
        return {"date": date_iso, "projected": 5, "eligible": 5, "errors": {}, "error": None}

    monkeypatch.setattr(bf, "_project_one_day", fake_worker)
    res = bf.run_range("project", "2026-07-01", "2026-07-06", day_jobs=2,
                       pg_url="dummy",
                       executor_factory=lambda: ThreadPoolExecutor(max_workers=2))
    # 07/04 Sat and 07/05 Sun are skipped by the business-day grid
    assert sorted(seen) == ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-06"]
    assert [r["date"] for r in res] == sorted(seen)          # results come back ordered
    assert sum(1 for r in res if r["error"]) == 1            # bad day isolated


def test_run_range_rejects_snapshot_phase():
    import pytest

    from SDRUtils._swappulse_scripts import backfill_stir_ladder as bf

    with pytest.raises(ValueError, match=r"project\|marks"):
        bf.run_range("snapshot", "2026-07-01", "2026-07-01")
