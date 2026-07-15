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
