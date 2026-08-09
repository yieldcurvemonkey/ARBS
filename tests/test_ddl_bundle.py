from __future__ import annotations

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import (
    _split_ddl_statements,
    _group_ddl_statements,
    _is_view_statement,
)


def test_split_ddl_statements():
    ddl = "ALTER TABLE t ADD COLUMN a INT;\nCREATE INDEX i ON t(a);\n"
    stmts = _split_ddl_statements(ddl)
    assert len(stmts) == 2
    assert stmts[0].startswith("ALTER TABLE t")
    assert stmts[1].startswith("CREATE INDEX i")


def test_is_view_statement():
    assert _is_view_statement("DROP VIEW IF EXISTS v;")
    assert _is_view_statement("CREATE OR REPLACE VIEW v AS SELECT 1;")
    assert _is_view_statement("  create view v as select 1;")
    assert not _is_view_statement("ALTER TABLE t ADD COLUMN a INT;")
    assert not _is_view_statement("CREATE INDEX i ON t(a);")


def test_view_drop_create_grouped_atomically():
    ddl = (
        "ALTER TABLE t ADD COLUMN a INT;\n"
        "DROP VIEW IF EXISTS v;\n"
        "CREATE OR REPLACE VIEW v AS SELECT 1;\n"
        "CREATE INDEX i ON t(a);\n"
    )
    groups = _group_ddl_statements(_split_ddl_statements(ddl))
    # ALTER alone | [DROP VIEW + CREATE VIEW] atomic | CREATE INDEX alone
    assert [len(g) for g in groups] == [1, 2, 1]
    assert groups[1][0].startswith("DROP VIEW")
    assert "CREATE OR REPLACE VIEW" in groups[1][1]


def test_consecutive_same_table_alters_are_batched():
    # One ACCESS EXCLUSIVE acquisition for a block of ADD COLUMNs on one table.
    ddl = "ALTER TABLE t ADD COLUMN a INT;\nALTER TABLE t ADD COLUMN b INT;\n"
    groups = _group_ddl_statements(_split_ddl_statements(ddl))
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_alters_on_different_tables_stay_separate():
    ddl = "ALTER TABLE t ADD COLUMN a INT;\nALTER TABLE u ADD COLUMN b INT;\n"
    groups = _group_ddl_statements(_split_ddl_statements(ddl))
    assert [len(g) for g in groups] == [1, 1]


def test_index_between_alters_breaks_the_batch():
    ddl = (
        "ALTER TABLE t ADD COLUMN a INT;\n"
        "CREATE INDEX i ON t(a);\n"
        "ALTER TABLE t ADD COLUMN b INT;\n"
    )
    groups = _group_ddl_statements(_split_ddl_statements(ddl))
    assert [len(g) for g in groups] == [1, 1, 1]


def test_multiline_create_view_grouped():
    ddl = "DROP VIEW IF EXISTS v;\nCREATE OR REPLACE VIEW v AS\n  SELECT a, b\n  FROM t;\n"
    groups = _group_ddl_statements(_split_ddl_statements(ddl))
    assert len(groups) == 1 and len(groups[0]) == 2


def test_comment_line_ending_in_semicolon_is_dropped():
    # The v2 schema has a comment line that ends in ';' (#333). It must not be
    # emitted as a statement (psycopg2: "can't execute an empty query").
    ddl = "-- Manual regrouping + notes. Dashboard-owned tables;\nCREATE TABLE t (a INT);\n"
    stmts = _split_ddl_statements(ddl)
    assert len(stmts) == 1
    assert stmts[0].startswith("CREATE TABLE t")


def test_no_blank_statements_in_real_schemas():
    from SDRUtils._swappulse_scripts._tape_schema_current import TAPE_SCHEMA_SQL_CURRENT
    for s in _split_ddl_statements(TAPE_SCHEMA_SQL_CURRENT):
        assert any(
            ln.strip() and not ln.strip().startswith("--")
            for ln in s.splitlines()
        ), f"blank/comment-only statement emitted: {s[:60]!r}"


def test_real_tape_schema_view_stays_atomic():
    # The real current-generation schema's display-view DROP+CREATE must land in one group.
    from SDRUtils._swappulse_scripts._tape_schema_current import TAPE_SCHEMA_SQL_CURRENT
    groups = _group_ddl_statements(_split_ddl_statements(TAPE_SCHEMA_SQL_CURRENT))
    view_groups = [g for g in groups if any(_is_view_statement(s) for s in g)]
    assert view_groups, "expected a view group in the current-generation schema"
    for g in view_groups:
        # every statement in a view group is a view op, and a DROP is paired with a CREATE
        assert all(_is_view_statement(s) for s in g)
        assert any(s.lstrip().upper().startswith("DROP VIEW") for s in g)
        assert any("VIEW" in s.upper() and "AS" in s.upper() for s in g)


from unittest.mock import patch, MagicMock
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import ensure_schema, TAPE_SCHEMA_SQL


def test_ensure_schema_forwards_lock_timeout():
    """ensure_schema passes lock_timeout_ms to _execute_ddl_bundle."""
    mock_engine = MagicMock()
    mock_engine.url = "postgresql://test/test"
    with patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._schema_already_current",
        return_value=False,
    ), patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._execute_ddl_bundle"
    ) as mock_ddl, patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._schema_ensured",
        set(),
    ):
        ensure_schema(mock_engine, lock_timeout_ms=90_000)
        for call in mock_ddl.call_args_list:
            assert call.kwargs.get("lock_timeout_ms") == 90_000 or \
                   (len(call.args) >= 3 and call.args[2] == 90_000), \
                f"lock_timeout_ms not forwarded: {call}"


def test_ensure_schema_skips_v1_bundle_by_default(monkeypatch):
    """v1 is the declared frozen rollback target. ensure_schema() must not
    issue the v1 DDL bundle (three CREATE TABLE, ten ADD COLUMN, eleven
    CREATE INDEX, and one unconditional CREATE OR REPLACE VIEW -- all
    ACCESS EXCLUSIVE) as a side effect of ensuring v3 exists, unless a
    caller explicitly opts in via ARBS_ENSURE_V1_TAPE=1."""
    monkeypatch.delenv("ARBS_ENSURE_V1_TAPE", raising=False)
    mock_engine = MagicMock()
    mock_engine.url = "postgresql://test/test-v1-default-off"
    with patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._schema_already_current",
        return_value=False,
    ), patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._execute_ddl_bundle"
    ) as mock_ddl, patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._schema_ensured",
        set(),
    ):
        ensure_schema(mock_engine)
        executed_ddls = [call.args[1] for call in mock_ddl.call_args_list]
        assert TAPE_SCHEMA_SQL not in executed_ddls, (
            "v1 DDL bundle executed with ARBS_ENSURE_V1_TAPE unset -- it must "
            "default OFF; v1 is the frozen rollback target and must not take "
            "ACCESS EXCLUSIVE locks as a side effect of ensuring v3."
        )
        assert len(executed_ddls) == 2, (
            f"expected exactly 2 DDL bundles (current-generation + monitoring) "
            f"with the v1 gate off, got {len(executed_ddls)}"
        )


def test_ensure_schema_runs_v1_bundle_when_opted_in(monkeypatch):
    """ARBS_ENSURE_V1_TAPE=1 lets a genuinely fresh environment that needs
    the v1 rollback path materialise it deliberately."""
    monkeypatch.setenv("ARBS_ENSURE_V1_TAPE", "1")
    mock_engine = MagicMock()
    mock_engine.url = "postgresql://test/test-v1-opt-in"
    with patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._schema_already_current",
        return_value=False,
    ), patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._execute_ddl_bundle"
    ) as mock_ddl, patch(
        "SDRUtils._swappulse_scripts.ingest_usdswaps_tape._schema_ensured",
        set(),
    ):
        ensure_schema(mock_engine)
        executed_ddls = [call.args[1] for call in mock_ddl.call_args_list]
        assert TAPE_SCHEMA_SQL in executed_ddls, (
            "v1 DDL bundle NOT executed with ARBS_ENSURE_V1_TAPE=1 -- the "
            "opt-in path is broken."
        )
        assert len(executed_ddls) == 3, (
            f"expected exactly 3 DDL bundles (v1 + current-generation + "
            f"monitoring) with the v1 gate on, got {len(executed_ddls)}"
        )
