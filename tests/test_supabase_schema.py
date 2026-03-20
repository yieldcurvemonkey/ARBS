"""Tests for Caching.supabase_schema — DDL management."""

import importlib

import pytest


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

    def test_schema_sql_uses_if_not_exists(self):
        from Caching.supabase_schema import SCHEMA_SQL
        assert "IF NOT EXISTS" in SCHEMA_SQL


class TestEnsureSchema:
    """ensure_schema() is a no-op when Supabase is explicitly disabled."""

    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import Caching.supabase_engine as eng
        importlib.reload(eng)
        from Caching.supabase_schema import ensure_schema
        # Should not raise — just returns False
        assert ensure_schema() is False

    def test_explicit_engine_runs_schema_only_once_per_engine(self, monkeypatch):
        import Caching.supabase_schema as schema_mod

        schema_mod = importlib.reload(schema_mod)
        monkeypatch.setattr(schema_mod, "SCHEMA_SQL", "CREATE TABLE t (id INT); CREATE INDEX i ON t (id);")

        class _FakeConn:
            def __init__(self):
                self.calls = 0

            def execute(self, stmt):
                _ = stmt
                self.calls += 1

        class _FakeEngine:
            def __init__(self, key: str):
                self.url = key
                self._conn = _FakeConn()

            def begin(self):
                return self

            def __enter__(self):
                return self._conn

            def __exit__(self, *args):
                return False

        engine = _FakeEngine("postgresql://example/a")
        other_engine = _FakeEngine("postgresql://example/b")

        assert schema_mod.ensure_schema(engine) is True
        assert schema_mod.ensure_schema(engine) is True
        assert engine._conn.calls == 2

        assert schema_mod.ensure_schema(other_engine) is True
        assert other_engine._conn.calls == 2
