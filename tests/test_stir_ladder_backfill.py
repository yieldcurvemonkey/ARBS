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
def test_code_vintage_is_a_12_hex_digest():
    from SDRUtils.stir_flow.vintage import UNKNOWN_VINTAGE, code_vintage

    v = code_vintage()
    assert isinstance(v, str) and v
    if v == UNKNOWN_VINTAGE:
        return
    assert len(v) == 12 and all(c in "0123456789abcdef" for c in v), v


def test_code_vintage_is_resolved_once():
    """Cached: re-hashing 19 modules per row would dominate a 6-month backfill."""
    from SDRUtils.stir_flow.vintage import code_vintage

    assert code_vintage() is code_vintage()


def test_code_vintage_sources_all_exist():
    """A typo'd path would hash as <missing> and silently never bump again."""
    import pathlib

    from SDRUtils.stir_flow import vintage

    missing = [rel for rel in vintage.VINTAGE_SOURCES
               if not (vintage._REPO / rel).is_file()]
    assert not missing, missing


def test_code_vintage_excludes_its_own_module_and_daylog():
    """Editing the hasher's prose, or stdout plumbing, must not invalidate a backfill."""
    from SDRUtils.stir_flow import vintage

    assert "SDRUtils/stir_flow/vintage.py" not in vintage.VINTAGE_SOURCES
    assert "SDRUtils/stir_flow/daylog.py" not in vintage.VINTAGE_SOURCES


def test_code_vintage_tracks_content_not_git_head(tmp_path, monkeypatch):
    """The stamp must change when a pipeline module changes, and ONLY then.

    The point of hashing contents instead of HEAD: a 6-month backfill runs for
    hours, and committing anything at all meanwhile would otherwise split the
    window into artificial vintages.
    """
    from SDRUtils.stir_flow import vintage

    src = tmp_path / "SDRUtils" / "stir_flow"
    src.mkdir(parents=True)
    (src / "a.py").write_text("ONE", encoding="utf-8")
    (src / "b.py").write_text("TWO", encoding="utf-8")
    monkeypatch.setattr(vintage, "_REPO", tmp_path)
    monkeypatch.setattr(vintage, "VINTAGE_SOURCES",
                        ("SDRUtils/stir_flow/a.py", "SDRUtils/stir_flow/b.py"))

    vintage.code_vintage.cache_clear()
    first = vintage.code_vintage()
    vintage.code_vintage.cache_clear()
    assert vintage.code_vintage() == first          # stable across calls

    (src / "b.py").write_text("TWO-CHANGED", encoding="utf-8")
    vintage.code_vintage.cache_clear()
    assert vintage.code_vintage() != first          # content change bumps it

    # a CRLF/LF checkout difference is not a logic change
    (src / "b.py").write_bytes(b"TWO-CHANGED")
    vintage.code_vintage.cache_clear()
    lf = vintage.code_vintage()
    (src / "b.py").write_bytes(b"TWO-CHANGED".replace(b"-", b"\r\n"))
    vintage.code_vintage.cache_clear()
    crlf_source = vintage.code_vintage()
    (src / "b.py").write_bytes(b"TWO-CHANGED".replace(b"-", b"\n"))
    vintage.code_vintage.cache_clear()
    assert vintage.code_vintage() == crlf_source, "CRLF must normalise to LF"
    assert lf != crlf_source                        # sanity: these differ in content

    # a deleted module must still move the stamp, not be silently skipped
    (src / "b.py").unlink()
    vintage.code_vintage.cache_clear()
    assert vintage.code_vintage() not in (first, lf, crlf_source)
    vintage.code_vintage.cache_clear()


def test_purge_stale_vintage_targets_other_vintages_only():
    from SDRUtils._swappulse_scripts import backfill_stir_direction_range as R

    conn = _RecordingConn()
    assert R.purge_stale_vintage(conn, "2026-01-12", "2026-07-29", "abc123") == 7
    sql, params = conn.log[0]
    assert f"DELETE FROM {R.DIRECTION_TABLE}" in sql
    assert "code_vintage IS DISTINCT FROM" in sql       # NULL-safe: pre-stamp rows too
    assert params == {"s": "2026-01-12", "e": "2026-07-29", "v": "abc123"}


def test_purge_is_skipped_when_any_day_errored(monkeypatch, capsys):
    """A day that errored wrote nothing, so purging would delete its previous rows
    and leave a hole indistinguishable from a genuinely empty session."""
    from concurrent.futures import ThreadPoolExecutor

    from SDRUtils._swappulse_scripts import backfill_stir_direction_range as R

    monkeypatch.setattr(R.psycopg2, "connect", lambda url: _DummyRangeConn())
    monkeypatch.setattr(R, "ensure_schema", lambda conn: None)
    monkeypatch.setattr(R, "write_tick_rows", lambda conn, stats: None)
    monkeypatch.setattr(R, "run_calibration", lambda conn, s, e, m: pd.DataFrame())
    purged = []
    monkeypatch.setattr(R, "purge_stale_vintage",
                        lambda conn, s, e, v: purged.append((s, e, v)) or 0)
    monkeypatch.setattr(R, "_classify_one_day", lambda job: {
        "date": job[0], "n": 0, "summary": {},
        "error": "boom" if job[0] == "2026-07-02" else None})

    R.run_range("2026-07-01", "2026-07-02", day_jobs=1, pg_url="dummy",
                purge_stale=True,
                executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert purged == []
    assert "purge SKIPPED" in capsys.readouterr().out


class _DummyRangeConn:
    def close(self):
        pass

    def cursor(self):
        raise AssertionError("purge must not run in this test")

    def commit(self):
        pass


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
