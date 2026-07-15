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
