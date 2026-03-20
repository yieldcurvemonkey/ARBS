"""DDL management for CORE cache Postgres tables."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from sqlalchemy import Engine
from sqlalchemy import text

from Caching.supabase_engine import get_engine

logger = logging.getLogger(__name__)

_SQL_PATH = Path(__file__).resolve().parent.parent / "sql" / "core_cache_schema.sql"
SCHEMA_SQL: str = _SQL_PATH.read_text(encoding="utf-8")
_schema_ready = False
_schema_lock = threading.Lock()
_schema_ready_by_engine: set[str] = set()


def _engine_cache_key(engine: Engine) -> str:
    url = getattr(engine, "url", None)
    if url is not None:
        render = getattr(url, "render_as_string", None)
        if callable(render):
            try:
                return str(render(hide_password=True))
            except TypeError:
                try:
                    return str(render())
                except Exception:
                    pass
        try:
            return str(url)
        except Exception:
            pass
    return f"{type(engine).__module__}.{type(engine).__qualname__}:{id(engine)}"


def _apply_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in SCHEMA_SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(text(stmt))


def ensure_schema(engine: Optional[Engine] = None) -> bool:
    """Create tables and indexes if they do not exist.

    Returns True if schema was applied, False if Supabase is disabled.
    """
    global _schema_ready

    active_engine = engine or get_engine()
    if active_engine is None:
        return False
    cache_key = _engine_cache_key(active_engine)

    if engine is None and (_schema_ready or cache_key in _schema_ready_by_engine):
        _schema_ready = True
        return True

    with _schema_lock:
        if _schema_ready or cache_key in _schema_ready_by_engine:
            if engine is None:
                _schema_ready = True
            return True
        _apply_schema(active_engine)
        _schema_ready_by_engine.add(cache_key)
        if engine is None:
            _schema_ready = True
        logger.info("CORE cache schema ensured for %s.", cache_key)
        return True
