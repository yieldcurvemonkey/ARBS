import datetime
import pandas as pd
import pytest
from SDRUtils._swappulse_scripts import _stir_flow_schema_v1 as schema
from SDRUtils.stir_flow.pricing import LegPricing
from SDRUtils.stir_flow.trade_selection import Unit


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


def _unit_df():
    return pd.DataFrame([dict(
        trade_id="T1", package_id="OUTRIGHT-T1", as_of_date=datetime.date(2026, 7, 10),
        execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        original_execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        trade_type="OUTRIGHT", rate_index_clean="FED_FUNDS",
        special_tenor_type="FOMC", fomc_meeting_label="JUL26",
        tenor_label="2M", forward_label=None, forward_start_years=0.0,
        effective_date=datetime.date(2026, 7, 29),
        expiration_date=datetime.date(2026, 9, 16),
        notional=3.7e9, risk=50_000.0, fixed_rate=0.03713,
        other_payment_ufro=13427.26854, pkg_ptp=None, pkg_pts=None,
        is_capped=False, is_block=False, is_off_date=False,
        leg_tape_label="FF FOMC JUL26", execution_session="NY_PM",
        package_structure="2M Outright", n_package_legs=1,
    )])


def test_classify_units_produces_row_and_handles_errors():
    from SDRUtils._swappulse_scripts import backfill_stir_direction as bf

    unit = Unit("T1", "OUTRIGHT", _unit_df(), None, True)

    class FakePricer:
        def price_leg(self, curve_name, ts, eff, mat, notional, fixed_rate=None):
            return LegPricing(3.717511, 22554.95, 50000.99)

    rows = bf.classify_units([unit], FakePricer(),
                             tick_lookup=lambda *a: None,
                             prev_rate_lookup=lambda *a: None)
    r = rows[0]
    assert r["unit_key"] == "T1"
    assert r["dealer_direction"] == "PAID" and r["dealer_bought"] is True
    assert r["curve_name"] == "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
    assert r["tenor_bucket"] == "FOMC_JUL26"

    class BoomPricer:
        def price_leg(self, *a, **k):
            raise ValueError("fixings gap")

    rows = bf.classify_units([unit], BoomPricer(),
                             tick_lookup=lambda *a: None,
                             prev_rate_lookup=lambda *a: None)
    r = rows[0]
    assert r["dealer_direction"] == "UNKNOWN"
    assert any(f.startswith("PRICING_ERROR") for f in r["quality_flags"])


def test_write_direction_rows_upsert_sql():
    from SDRUtils._swappulse_scripts import backfill_stir_direction as bf
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

    def fake_execute_values(cur, sql, argslist, template=None):
        captured["sql"] = sql
        captured["n"] = len(argslist)

    bf._execute_values = fake_execute_values  # inject
    bf.write_direction_rows(FakeConn(), [dict(bf.EMPTY_DIRECTION_ROW, unit_key="T1",
                                              as_of_date=datetime.date(2026, 7, 10),
                                              execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"))])
    assert "ON CONFLICT (unit_key) DO UPDATE" in captured["sql"]
    assert captured["n"] == 1 and captured["committed"]
