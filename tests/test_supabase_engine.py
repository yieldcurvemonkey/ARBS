"""Tests for Caching.supabase_engine — singleton SQLAlchemy engine."""

import os
import threading

import pytest


class TestSupabaseEnabled:
    """ARBS_SUPABASE_ENABLED flag tracks whether a database URL is configured."""

    def test_disabled_when_no_url(self, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        # Force module reload to pick up env change
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.SUPABASE_ENABLED is False

    def test_enabled_when_url_set(self, monkeypatch):
        monkeypatch.setenv("ARBS_DATABASE_URL", "postgresql://user:pass@host:6543/db")
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.SUPABASE_ENABLED is True


class TestGetEngine:
    """get_engine() returns a singleton SQLAlchemy Engine, or None if disabled."""

    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.get_engine() is None

    def test_returns_engine_when_enabled(self, monkeypatch):
        monkeypatch.setenv(
            "ARBS_DATABASE_URL",
            "postgresql://user:pass@localhost:6543/testdb",
        )
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        engine = mod.get_engine()
        assert engine is not None
        from sqlalchemy import Engine
        assert isinstance(engine, Engine)

    def test_singleton_returns_same_instance(self, monkeypatch):
        monkeypatch.setenv(
            "ARBS_DATABASE_URL",
            "postgresql://user:pass@localhost:6543/testdb",
        )
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        e1 = mod.get_engine()
        e2 = mod.get_engine()
        assert e1 is e2

    def test_thread_safe_singleton(self, monkeypatch):
        monkeypatch.setenv(
            "ARBS_DATABASE_URL",
            "postgresql://user:pass@localhost:6543/testdb",
        )
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
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as mod
        importlib.reload(mod)
        assert mod.get_raw_connection() is None
