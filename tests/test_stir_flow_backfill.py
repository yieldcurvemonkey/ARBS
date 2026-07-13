from SDRUtils._swappulse_scripts import _stir_flow_schema_v1 as schema


def test_schema_ddl_columns():
    ddl = "\n".join(schema.DDL_STATEMENTS)
    assert "CREATE TABLE IF NOT EXISTS arbs_stir_direction_v1" in ddl
    assert "CREATE TABLE IF NOT EXISTS arbs_stir_tick_size_v1" in ddl
    for col in (
        "unit_key", "trade_id", "package_id", "classification_method",
        "dealer_direction", "direction_confidence", "dealer_bought",
        "dealer_charge_bps", "curve_suspect_trade", "quality_flags",
        "repriced_npv", "reported_ptp", "reported_opa", "p_flip",
        "spread_to_mid_bps", "structure_dv01", "tenor_query",
    ):
        assert col in ddl, col
    for col in (
        "tenor_bucket", "structure_type", "dv01_bucket", "median_tick_bps",
        "disp_vw", "disp_jns", "curve_suspect", "amihud",
        "median_dealer_charge_bps", "futures_min_tick_bps",
    ):
        assert col in ddl, col


def test_ensure_schema_executes_all(monkeypatch):
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
