"""Tests for Caching.supabase_engine — singleton SQLAlchemy engine."""

import threading

import pytest


class TestSupabaseEnabled:
    """ARBS_SUPABASE_ENABLED controls whether the fallback config is active."""

    def test_enabled_by_default_with_ingest_fallback(self, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_DATABASE_URL", raising=False)
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        # Force module reload to pick up env change
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.SUPABASE_ENABLED is True
        assert mod.get_database_url() == (
            "postgresql://postgres.rdobtpugtnmefxplgwyp:0rbZUh8y0Fsvdlry"
            "@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        )

    def test_disabled_when_explicitly_opted_out(self, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_DATABASE_URL", raising=False)
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.SUPABASE_ENABLED is False

    def test_explicit_url_override_wins(self, monkeypatch):
        monkeypatch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@host:6543/db")
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.SUPABASE_ENABLED is True
        assert mod.get_database_url() == "postgresql://user:pass@host:6543/db"


class TestGetEngine:
    """get_engine() returns a singleton SQLAlchemy Engine, or None if disabled."""

    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "false")
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.get_engine() is None

    def test_returns_engine_when_enabled(self, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@localhost:6543/testdb")
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        engine = mod.get_engine()
        assert engine is not None
        from sqlalchemy import Engine
        assert isinstance(engine, Engine)

    def test_singleton_returns_same_instance(self, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@localhost:6543/testdb")
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        e1 = mod.get_engine()
        e2 = mod.get_engine()
        assert e1 is e2

    def test_thread_safe_singleton(self, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@localhost:6543/testdb")
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        engines = []

        def grab():
            engines.append(mod.get_engine())

        threads = [threading.Thread(target=grab) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(e is engines[0] for e in engines)


class TestGetRawConnection:
    """get_raw_connection() provides a psycopg2 connection for batch ops."""

    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.get_raw_connection() is None
