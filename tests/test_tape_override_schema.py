"""DDL / schema tests for the manual-regrouping + notes tables (2026-07-08).

Mirrors the DB harness in test_ingest_usdswaps_tape_writepath.py: consumes the
``pg_test_url`` fixture, marks DB-dependent tests ``@pytest.mark.db``, and
asserts via engine.connect() + text().
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts import ingest_usdswaps_tape as _ing
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import (
    _schema_already_current,
    ensure_schema,
)
from SDRUtils._swappulse_scripts._tape_schema_v2 import (
    DISPLAY_VIEW_V2,
    LEGS_TABLE_V2,
    NOTES_TABLE_V2,
    OVERRIDE_HISTORY_TABLE_V2,
    OVERRIDE_MEMBERS_TABLE_V2,
    OVERRIDES_TABLE_V2,
    PACKAGES_TABLE_V2,
    TAPE_SCHEMA_SQL_V2,
)


@pytest.fixture
def override_engine(pg_test_url):
    """Drop the four new objects, force ensure_schema to re-run, return engine."""
    engine = create_engine(pg_test_url)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_MEMBERS_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_HISTORY_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {NOTES_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDES_TABLE_V2} CASCADE"))
    _ing._schema_ensured.discard(str(engine.url))
    ensure_schema(engine)
    return engine


@pytest.mark.db
def test_override_tables_created(override_engine):
    expected = {
        OVERRIDES_TABLE_V2,
        OVERRIDE_MEMBERS_TABLE_V2,
        OVERRIDE_HISTORY_TABLE_V2,
        NOTES_TABLE_V2,
    }
    with override_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name = ANY(:names)"
            ),
            {"names": list(expected)},
        ).fetchall()
    found = {r[0] for r in rows}
    assert expected <= found, f"missing tables: {expected - found}"


@pytest.mark.db
def test_group_override_requires_two_trades(override_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDES_TABLE_V2} "
                    "(override_type, trade_ids, created_by) "
                    "VALUES ('GROUP', ARRAY['T1'], 'pytest')"
                )
            )
    with override_engine.begin() as conn:
        oid = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} "
                "(override_type, trade_ids, created_by) "
                "VALUES ('GROUP', ARRAY['T1','T2'], 'pytest') RETURNING override_id"
            )
        ).scalar()
    assert oid is not None


@pytest.mark.db
def test_override_type_check(override_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDES_TABLE_V2} "
                    "(override_type, trade_ids, created_by) "
                    "VALUES ('FOO', ARRAY['T1','T2'], 'pytest')"
                )
            )


@pytest.mark.db
def test_override_members_one_active_per_trade(override_engine):
    from sqlalchemy.exc import IntegrityError

    with override_engine.begin() as conn:
        oid1 = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} (override_type, trade_ids, created_by) "
                "VALUES ('GROUP', ARRAY['TX','TY'], 'pytest') RETURNING override_id"
            )
        ).scalar()
        oid2 = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} (override_type, trade_ids, created_by) "
                "VALUES ('GROUP', ARRAY['TX','TZ'], 'pytest') RETURNING override_id"
            )
        ).scalar()
        conn.execute(
            text(
                f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                "(trade_id, override_id, override_type, is_active) "
                "VALUES ('TX', :oid, 'GROUP', TRUE)"
            ),
            {"oid": oid1},
        )
    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                    "(trade_id, override_id, override_type, is_active) "
                    "VALUES ('TX', :oid, 'GROUP', TRUE)"
                ),
                {"oid": oid2},
            )
    # inactive duplicate is allowed (partial index is WHERE is_active)
    with override_engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                "(trade_id, override_id, override_type, is_active) "
                "VALUES ('TX', :oid, 'GROUP', FALSE)"
            ),
            {"oid": oid2},
        )


@pytest.mark.db
def test_notes_target_type_check(override_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {NOTES_TABLE_V2} "
                    "(target_type, target_id, author, body) "
                    "VALUES ('FOO', 'T1', 'pytest', 'hi')"
                )
            )


def test_latest_migration_cols_includes_overrides_table():
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import _LATEST_MIGRATION_COLS

    assert ("arbs_usd_swap_tape_overrides_v2", "override_id") in _LATEST_MIGRATION_COLS


@pytest.mark.db
def test_schema_not_current_when_overrides_missing(pg_test_url):
    engine = create_engine(pg_test_url)
    _ing._schema_ensured.discard(str(engine.url))
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_MEMBERS_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_HISTORY_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {NOTES_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDES_TABLE_V2} CASCADE"))
    # Missing overrides table -> sentinel probe finds no row -> NOT current.
    assert _schema_already_current(engine) is False
    ensure_schema(engine)
    assert _schema_already_current(engine) is True


@pytest.mark.db
def test_display_view_has_override_columns(override_engine):
    expected = {"override_map", "manual_package_id", "override_type",
                "has_notes", "notes_count"}
    with override_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :v"
            ),
            {"v": DISPLAY_VIEW_V2},
        ).fetchall()
    cols = {r[0] for r in rows}
    assert expected <= cols, f"view missing columns: {expected - cols}"


@pytest.mark.db
def test_view_legs_json_byte_identical_after_override(override_engine):
    with override_engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {PACKAGES_TABLE_V2} "
                "(package_id, as_of_date, execution_start, execution_end, legs_count) "
                "VALUES ('PKG_OV_1','2026-07-08',"
                "'2026-07-08T12:00:00Z','2026-07-08T12:00:00Z',2)"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {LEGS_TABLE_V2} "
                "(trade_id, package_id, leg_order, as_of_date, execution_timestamp) VALUES "
                "('TID_A','PKG_OV_1',0,'2026-07-08','2026-07-08T12:00:00Z'),"
                "('TID_B','PKG_OV_1',1,'2026-07-08','2026-07-08T12:00:00Z')"
            )
        )
    with override_engine.connect() as conn:
        before = conn.execute(
            text(f"SELECT legs_json::text FROM {DISPLAY_VIEW_V2} WHERE package_id='PKG_OV_1'")
        ).scalar()
    with override_engine.begin() as conn:
        oid = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} "
                "(override_type, manual_package_id, trade_ids, created_by) "
                "VALUES ('GROUP','SMO-20260708-DEADBEEF', ARRAY['TID_A','TID_B'], 'pytest') "
                "RETURNING override_id"
            )
        ).scalar()
        conn.execute(
            text(
                f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                "(trade_id, override_id, override_type, manual_package_id, is_active) "
                "VALUES ('TID_A', :oid, 'GROUP', 'SMO-20260708-DEADBEEF', TRUE)"
            ),
            {"oid": oid},
        )
    with override_engine.connect() as conn:
        after_legs, override_map, manual_pkg, ov_type = conn.execute(
            text(
                f"SELECT legs_json::text, override_map, manual_package_id, override_type "
                f"FROM {DISPLAY_VIEW_V2} WHERE package_id='PKG_OV_1'"
            )
        ).fetchone()
    assert after_legs == before, "legs_json changed after override attach"
    assert override_map is not None
    assert override_map.get("TID_A") == str(oid)
    assert manual_pkg == "SMO-20260708-DEADBEEF"
    assert ov_type == "GROUP"


@pytest.mark.db
def test_view_notes_flags(override_engine):
    with override_engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {PACKAGES_TABLE_V2} "
                "(package_id, as_of_date, execution_start, execution_end, legs_count) "
                "VALUES ('PKG_NOTE_1','2026-07-08',"
                "'2026-07-08T12:00:00Z','2026-07-08T12:00:00Z',1)"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {LEGS_TABLE_V2} "
                "(trade_id, package_id, leg_order, as_of_date, execution_timestamp) "
                "VALUES ('TID_N','PKG_NOTE_1',0,'2026-07-08','2026-07-08T12:00:00Z')"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {NOTES_TABLE_V2} (target_type, target_id, author, body) "
                "VALUES ('PACKAGE','PKG_NOTE_1','pytest','watch this')"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {NOTES_TABLE_V2} (target_type, target_id, author, body) "
                "VALUES ('TRADE','TID_N','pytest','leg note')"
            )
        )
    with override_engine.connect() as conn:
        has_notes, notes_count = conn.execute(
            text(f"SELECT has_notes, notes_count FROM {DISPLAY_VIEW_V2} WHERE package_id='PKG_NOTE_1'")
        ).fetchone()
    assert has_notes is True
    assert notes_count == 2


@pytest.mark.db
def test_view_plan_index_paths_and_cardinality(override_engine):
    with override_engine.begin() as conn:
        for i in range(6):
            conn.execute(
                text(
                    f"INSERT INTO {PACKAGES_TABLE_V2} "
                    "(package_id, as_of_date, execution_start, execution_end, legs_count) "
                    "VALUES (:pid,'2026-07-08',:ts,:ts,1)"
                ),
                {"pid": f"PKG_PLAN_{i}", "ts": f"2026-07-08T12:0{i}:00Z"},
            )
            conn.execute(
                text(
                    f"INSERT INTO {LEGS_TABLE_V2} "
                    "(trade_id, package_id, leg_order, as_of_date, execution_timestamp) "
                    "VALUES (:tid,:pid,0,'2026-07-08',:ts)"
                ),
                {"tid": f"TID_PLAN_{i}", "pid": f"PKG_PLAN_{i}", "ts": f"2026-07-08T12:0{i}:00Z"},
            )
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDES_TABLE_V2} (override_type, trade_ids, created_by) "
                    "VALUES ('SPLIT', ARRAY[:tid], 'pytest') RETURNING override_id"
                ),
                {"tid": f"TID_PLAN_{i}"},
            )

    with override_engine.connect() as conn:
        baseline = conn.execute(text(f"SELECT count(*) FROM {PACKAGES_TABLE_V2}")).scalar()
        view_rows = conn.execute(text(f"SELECT count(*) FROM {DISPLAY_VIEW_V2}")).scalar()
        conn.execute(text("SET enable_seqscan = off"))
        conn.execute(text("SET enable_bitmapscan = off"))
        plan_json = conn.execute(
            text(
                f"EXPLAIN (ANALYZE, FORMAT JSON) "
                f"SELECT * FROM {DISPLAY_VIEW_V2} d "
                f"WHERE d.execution_start < NOW() "
                f"ORDER BY d.execution_start DESC NULLS LAST LIMIT 201"
            )
        ).scalar()

    # cardinality unchanged: exactly one display row per package
    assert view_rows == baseline

    plan_text = json.dumps(plan_json)
    assert "idx_tape_v2_packages_exec_start" in plan_text, \
        "outer package scan not using idx_tape_v2_packages_exec_start"
    assert "uq_tape_v2_override_members_active_trade" in plan_text, \
        "members probe not served by its unique index (per-package re-scan regression?)"

    def _walk(node):
        yield node
        for child in node.get("Plans", []) or []:
            yield from _walk(child)

    nodes = list(_walk(plan_json[0]["Plan"]))
    member_seqscans = [
        n for n in nodes
        if n.get("Node Type") == "Seq Scan"
        and n.get("Relation Name") == OVERRIDE_MEMBERS_TABLE_V2
    ]
    assert not member_seqscans, "override_members seq-scanned — plan regression"


def test_view_ddl_contains_override_and_notes_columns():
    """Fast, unmarked regression guard (no DB required).

    All the Step-2 acceptance tests above are ``@pytest.mark.db`` and skip
    in environments without PG_TEST_URL/DATABASE_URL (this one included).
    This assertion inspects the generated view DDL string directly so the
    5 new columns + the manual_package_id COALESCE resolution have a fast,
    always-running regression guard.
    """
    view_sql = TAPE_SCHEMA_SQL_V2.split(f"CREATE OR REPLACE VIEW {DISPLAY_VIEW_V2}")[1]
    for col in ("override_map", "manual_package_id", "override_type",
                "has_notes", "notes_count"):
        assert col in view_sql, f"view DDL missing column {col!r}"
    assert "COALESCE(l.manual_package_id, ml.manual_package_id) AS manual_package_id" in view_sql
    # exactly one manual_package_id *output* column at the OUTER SELECT
    # level (the nested legs/notes LATERAL subqueries have their own
    # ``AS manual_package_id`` aliases, which are fine — a duplicate only
    # breaks the DDL if it appears twice in the outer view's SELECT list).
    outer_select = view_sql.split(f"FROM {PACKAGES_TABLE_V2} p")[0]
    assert "ml.manual_package_id," not in outer_select, (
        "standalone ml.manual_package_id projection must be removed from "
        "the outer SELECT (collides with the COALESCE column)"
    )
    assert outer_select.count("AS manual_package_id") == 1
