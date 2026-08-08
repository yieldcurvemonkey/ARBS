"""Tests for Caching.supabase_schema — DDL management.

The splitting/grouping cases mirror ``tests/test_ddl_bundle.py``, which pins the
same behaviour for the tape's copy. They are duplicated rather than shared
because ``Caching`` is the lower layer and must not import ``SDRUtils``; keeping
the assertions identical is how the two copies are kept from drifting.
"""

import importlib

import pytest

from Caching.supabase_schema import (
    declared_objects,
    group_ddl_statements,
    split_ddl_statements,
)


class TestSchemaSQL:
    """SCHEMA_SQL constant contains valid DDL."""

    def test_schema_sql_is_string(self):
        from Caching.supabase_schema import SCHEMA_SQL
        assert isinstance(SCHEMA_SQL, str)

    def test_schema_sql_contains_all_tables(self):
        from Caching.supabase_schema import SCHEMA_SQL
        assert "curve_snapshots" in SCHEMA_SQL
        assert "curve_intraday_blocks" in SCHEMA_SQL
        assert "curve_analytics_blocks" in SCHEMA_SQL
        assert "arbs_kv_cache_v1" in SCHEMA_SQL
        assert "arbs_computed_timeseries_blocks_v1" in SCHEMA_SQL
        assert "arbs_swaption_cube_blocks_v1" in SCHEMA_SQL

    def test_schema_sql_uses_if_not_exists(self):
        from Caching.supabase_schema import SCHEMA_SQL
        assert "IF NOT EXISTS" in SCHEMA_SQL


class TestSplitter:
    """Ported from ingest_usdswaps_tape; replaces a naive ``str.split(';')``."""

    def test_splits_on_semicolon_terminated_lines(self):
        stmts = split_ddl_statements("ALTER TABLE t ADD COLUMN a INT;\nCREATE INDEX i ON t(a);\n")
        assert len(stmts) == 2
        assert stmts[0].startswith("ALTER TABLE t")
        assert stmts[1].startswith("CREATE INDEX i")

    def test_comment_line_ending_in_a_semicolon_is_dropped(self):
        """A naive split(';') emits an empty chunk here, and psycopg2 rejects it."""
        ddl = "-- Dashboard-owned tables;\nCREATE TABLE t (a INT);\n"
        stmts = split_ddl_statements(ddl)
        assert len(stmts) == 1
        assert stmts[0].startswith("CREATE TABLE t")

    def test_the_real_bundle_emits_no_blank_statements(self):
        from Caching.supabase_schema import SCHEMA_SQL

        for s in split_ddl_statements(SCHEMA_SQL):
            assert any(
                ln.strip() and not ln.strip().startswith("--") for ln in s.splitlines()
            ), f"blank/comment-only statement emitted: {s[:60]!r}"

    def test_the_real_bundle_never_splits_a_create_table_in_half(self):
        """The property the old ``split(';')`` had by luck, asserted."""
        from Caching.supabase_schema import SCHEMA_SQL

        for s in split_ddl_statements(SCHEMA_SQL):
            if s.upper().lstrip().startswith("CREATE TABLE"):
                assert s.count("(") == s.count(")"), s[:80]
                assert s.rstrip().endswith(";")


class TestGrouping:
    def test_consecutive_alters_on_one_table_batch_into_one_lock(self):
        ddl = "ALTER TABLE t ADD COLUMN a INT;\nALTER TABLE t ADD COLUMN b INT;\n"
        groups = group_ddl_statements(split_ddl_statements(ddl))
        assert [len(g) for g in groups] == [2]

    def test_alters_on_different_tables_stay_separate(self):
        ddl = "ALTER TABLE t ADD COLUMN a INT;\nALTER TABLE u ADD COLUMN b INT;\n"
        assert [len(g) for g in group_ddl_statements(split_ddl_statements(ddl))] == [1, 1]

    def test_view_drop_and_create_stay_atomic(self):
        ddl = "DROP VIEW IF EXISTS v;\nCREATE OR REPLACE VIEW v AS SELECT 1;\n"
        groups = group_ddl_statements(split_ddl_statements(ddl))
        assert [len(g) for g in groups] == [2]

    def test_a_leading_comment_block_does_not_defeat_the_batching(self):
        """The real bundle's first ALTER has five comment lines glued to its front."""
        ddl = (
            "-- why this column exists\n"
            "-- second line of the reason\n"
            "ALTER TABLE t ADD COLUMN a INT;\n"
            "ALTER TABLE t ADD COLUMN b INT;\n"
        )
        assert [len(g) for g in group_ddl_statements(split_ddl_statements(ddl))] == [2]

    def test_the_real_bundle_batches_the_two_snapshot_alters(self):
        """Both spline ADD COLUMNs hit arbs_curve_snapshots_v1 — one lock, not two."""
        from Caching.supabase_schema import SCHEMA_SQL

        groups = group_ddl_statements(split_ddl_statements(SCHEMA_SQL))
        alter_groups = [g for g in groups if "ALTER TABLE" in g[0].upper()]
        assert len(alter_groups) == 1
        assert len(alter_groups[0]) == 2

    def test_the_real_bundle_is_many_short_transactions_not_one_long_one(self):
        from Caching.supabase_schema import SCHEMA_SQL

        assert len(group_ddl_statements(split_ddl_statements(SCHEMA_SQL))) > 10


class TestDeclaredObjects:
    def test_derives_tables_columns_and_indexes_from_the_sql(self):
        ddl = (
            "CREATE TABLE IF NOT EXISTS arbs_x_v1 (a INT);\n"
            "ALTER TABLE arbs_x_v1 ADD COLUMN IF NOT EXISTS b DATE;\n"
            "CREATE INDEX IF NOT EXISTS idx_x ON arbs_x_v1 (a);\n"
        )
        tables, columns, indexes = declared_objects(ddl)
        assert tables == {"arbs_x_v1"}
        assert columns == {("arbs_x_v1", "b")}
        assert indexes == {"idx_x"}

    def test_the_real_bundle_declares_what_it_creates(self):
        from Caching.supabase_schema import SCHEMA_SQL

        tables, columns, indexes = declared_objects(SCHEMA_SQL)
        assert "arbs_curve_snapshots_v1" in tables
        assert "arbs_swaption_cube_blocks_v1" in tables
        # the ALTER-added columns must be in the marker set, or a currency check
        # would short-circuit past an unapplied migration
        assert ("arbs_curve_snapshots_v1", "spline_knots") in columns
        assert ("arbs_curve_snapshots_v1", "spline_endpoints") in columns
        assert "idx_snapshots_tags" in indexes


# ── fakes shared by the ensure_schema tests ───────────────────────────────


class _FakeConn:
    def __init__(self, owner):
        self.owner = owner

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.owner.statements.append(sql)
        if "set_config" in sql:
            return None
        if sql.upper().startswith(("CREATE ", "ALTER ", "DROP ")):
            self.owner.ddl.append(sql)
        return _FakeResult(self.owner.currency_rows(sql, dict(params or {})))


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeEngine:
    """Enough of an Engine for ensure_schema, with a switchable 'already current'."""

    def __init__(self, key: str, *, already_current: bool = False):
        self.url = key
        self.statements: list[str] = []
        self.ddl: list[str] = []
        self.transactions = 0
        self._already_current = already_current

    def currency_rows(self, sql: str, params: dict):
        if not self._already_current:
            return []
        if "information_schema.tables" in sql:
            return [(n,) for n in (params.get("names") or [])]
        if "information_schema.columns" in sql:
            from Caching.supabase_schema import SCHEMA_SQL, declared_objects

            _, cols, _ = declared_objects(SCHEMA_SQL)
            return list(cols)
        if "pg_indexes" in sql:
            return [(n,) for n in (params.get("names") or [])]
        return []

    def begin(self):
        self.transactions += 1
        return self

    def connect(self):
        return self

    def __enter__(self):
        return _FakeConn(self)

    def __exit__(self, *args):
        return False


class TestEnsureSchema:
    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import Caching.supabase_engine as eng
        importlib.reload(eng)
        import Caching.supabase_schema as schema_mod
        schema_mod = importlib.reload(schema_mod)
        assert schema_mod.ensure_schema() is False

    def test_runs_once_per_engine_and_caches(self, monkeypatch):
        import Caching.supabase_schema as schema_mod

        schema_mod = importlib.reload(schema_mod)
        monkeypatch.setattr(
            schema_mod,
            "SCHEMA_SQL",
            "CREATE TABLE arbs_t_v1 (id INT);\nCREATE INDEX idx_t ON arbs_t_v1 (id);\n",
        )
        engine = _FakeEngine("postgresql://example/a")
        other = _FakeEngine("postgresql://example/b")

        assert schema_mod.ensure_schema(engine) is True
        assert len(engine.ddl) == 2
        assert schema_mod.ensure_schema(engine) is True
        assert len(engine.ddl) == 2, "the per-engine cache did not hold"

        assert schema_mod.ensure_schema(other) is True
        assert len(other.ddl) == 2

    def test_each_group_gets_its_own_transaction_with_a_lock_timeout(self, monkeypatch):
        """One transaction for the whole bundle is the pattern that deadlocked."""
        import Caching.supabase_schema as schema_mod

        schema_mod = importlib.reload(schema_mod)
        monkeypatch.setattr(
            schema_mod,
            "SCHEMA_SQL",
            "CREATE TABLE arbs_t_v1 (id INT);\nCREATE INDEX idx_t ON arbs_t_v1 (id);\n",
        )
        engine = _FakeEngine("postgresql://example/txn")
        schema_mod.ensure_schema(engine)

        assert engine.transactions == 2, "the bundle ran in one transaction"
        lock_stmts = [s for s in engine.statements if "lock_timeout" in s]
        assert len(lock_stmts) == 2
        assert all("true" in s for s in lock_stmts), "lock_timeout was not transaction-local"

    def test_a_current_schema_skips_the_ddl_entirely(self, monkeypatch):
        """The read paths call ensure_schema; they must not take ACCESS EXCLUSIVE."""
        import Caching.supabase_schema as schema_mod

        schema_mod = importlib.reload(schema_mod)
        engine = _FakeEngine("postgresql://example/current", already_current=True)
        assert schema_mod.ensure_schema(engine) is True
        assert engine.ddl == [], f"DDL ran against an already-current schema: {engine.ddl}"
        assert engine.transactions == 0

    def test_an_unprovable_currency_check_runs_the_ddl(self, monkeypatch):
        """'I could not prove it is current' must mean 'apply it', never 'assume'."""
        import Caching.supabase_schema as schema_mod

        schema_mod = importlib.reload(schema_mod)
        monkeypatch.setattr(schema_mod, "SCHEMA_SQL", "CREATE TABLE arbs_t_v1 (id INT);\n")

        class _Exploding(_FakeEngine):
            def currency_rows(self, sql, params):
                if "information_schema" in sql or "pg_indexes" in sql:
                    raise RuntimeError("no permission on information_schema")
                return []

        engine = _Exploding("postgresql://example/boom")
        assert schema_mod.ensure_schema(engine) is True
        assert len(engine.ddl) == 1

    def test_lock_contention_is_retried_then_gives_up(self, monkeypatch):
        import Caching.supabase_schema as schema_mod

        schema_mod = importlib.reload(schema_mod)
        monkeypatch.setattr(schema_mod, "time", _NoSleep())
        attempts = {"n": 0}

        class _Contended(_FakeEngine):
            def __enter__(self):
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise RuntimeError("canceling statement due to lock timeout")
                return _FakeConn(self)

        engine = _Contended("postgresql://example/lock")
        schema_mod.apply_ddl_bundle(engine, "CREATE TABLE arbs_t_v1 (id INT);\n")
        assert attempts["n"] == 3

        attempts["n"] = 0

        class _AlwaysContended(_Contended):
            def __enter__(self):
                attempts["n"] += 1
                raise RuntimeError("deadlock detected")

        with pytest.raises(RuntimeError):
            schema_mod.apply_ddl_bundle(
                _AlwaysContended("postgresql://example/dead"),
                "CREATE TABLE arbs_t_v1 (id INT);\n",
                max_attempts=3,
            )
        assert attempts["n"] == 3

    def test_a_non_lock_error_is_not_retried(self, monkeypatch):
        import Caching.supabase_schema as schema_mod

        schema_mod = importlib.reload(schema_mod)
        monkeypatch.setattr(schema_mod, "time", _NoSleep())
        attempts = {"n": 0}

        class _Broken(_FakeEngine):
            def __enter__(self):
                attempts["n"] += 1
                raise RuntimeError("syntax error at or near")

        with pytest.raises(RuntimeError):
            schema_mod.apply_ddl_bundle(
                _Broken("postgresql://example/syntax"), "CREATE TABLE arbs_t_v1 (id INT);\n"
            )
        assert attempts["n"] == 1


class _NoSleep:
    @staticmethod
    def sleep(_seconds):
        return None
