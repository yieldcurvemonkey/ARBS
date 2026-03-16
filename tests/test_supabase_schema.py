"""Tests for Caching.supabase_schema — DDL management."""

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
        assert "arbs_kv_cache_v1" in SCHEMA_SQL

    def test_schema_sql_uses_if_not_exists(self):
        from Caching.supabase_schema import SCHEMA_SQL
        assert "IF NOT EXISTS" in SCHEMA_SQL


class TestEnsureSchema:
    """ensure_schema() is a no-op when Supabase is explicitly disabled."""

    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)
        from Caching.supabase_schema import ensure_schema
        # Should not raise — just returns False
        assert ensure_schema() is False
