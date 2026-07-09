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
    from SDRUtils._swappulse_scripts._tape_schema_v2 import TAPE_SCHEMA_SQL_V2
    for s in _split_ddl_statements(TAPE_SCHEMA_SQL_V2):
        assert any(
            ln.strip() and not ln.strip().startswith("--")
            for ln in s.splitlines()
        ), f"blank/comment-only statement emitted: {s[:60]!r}"


def test_real_tape_schema_view_stays_atomic():
    # The real v2 schema's display-view DROP+CREATE must land in one group.
    from SDRUtils._swappulse_scripts._tape_schema_v2 import TAPE_SCHEMA_SQL_V2
    groups = _group_ddl_statements(_split_ddl_statements(TAPE_SCHEMA_SQL_V2))
    view_groups = [g for g in groups if any(_is_view_statement(s) for s in g)]
    assert view_groups, "expected a view group in the v2 schema"
    for g in view_groups:
        # every statement in a view group is a view op, and a DROP is paired with a CREATE
        assert all(_is_view_statement(s) for s in g)
        assert any(s.lstrip().upper().startswith("DROP VIEW") for s in g)
        assert any("VIEW" in s.upper() and "AS" in s.upper() for s in g)
