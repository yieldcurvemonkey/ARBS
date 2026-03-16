"""Singleton SQLAlchemy engine for Supabase/Postgres L2 cache.

Configuration precedence:
    1. ``ARBS_DATABASE_URL`` full PostgreSQL connection string
    2. ``SUPABASE_DATABASE_URL`` full PostgreSQL connection string
    3. ``SWAPPULSE_DB_*`` parts, defaulting to the same hard-coded Supabase
       pooler values used by the SwapPulse ingest scripts

Set ``ARBS_SUPABASE_ENABLED=0`` to disable the CORE cache L2 explicitly.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from sqlalchemy import Engine, create_engine

logger = logging.getLogger(__name__)

DEFAULT_DB_HOST = "aws-0-us-east-1.pooler.supabase.com"
DEFAULT_DB_PORT = "6543"
DEFAULT_DB_NAME = "postgres"
DEFAULT_DB_USER = "postgres.rdobtpugtnmefxplgwyp"
DEFAULT_DB_PASSWORD = "0rbZUh8y0Fsvdlry"


def _env_enabled(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in {"0", "false", "f", "no", "n", "off"}


def get_database_url() -> Optional[str]:
    """Resolve the database URL with ingest-script-compatible defaults."""
    explicit_url = os.environ.get("ARBS_DATABASE_URL") or os.environ.get("SUPABASE_DATABASE_URL")
    if explicit_url:
        return explicit_url

    host = os.environ.get("SWAPPULSE_DB_HOST", DEFAULT_DB_HOST)
    port = os.environ.get("SWAPPULSE_DB_PORT", DEFAULT_DB_PORT)
    dbname = os.environ.get("SWAPPULSE_DB_NAME", DEFAULT_DB_NAME)
    user = os.environ.get("SWAPPULSE_DB_USER", DEFAULT_DB_USER)
    password = os.environ.get("SWAPPULSE_DB_PASSWORD", DEFAULT_DB_PASSWORD)
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


SUPABASE_ENABLED: bool = _env_enabled("ARBS_SUPABASE_ENABLED", True)
_DATABASE_URL: Optional[str] = get_database_url() if SUPABASE_ENABLED else None
SUPABASE_ENABLED = SUPABASE_ENABLED and bool(_DATABASE_URL)

_engine: Optional[Engine] = None
_lock = threading.Lock()


def get_engine() -> Optional[Engine]:
    """Return the singleton SQLAlchemy engine, or None if disabled."""
    global _engine
    if not SUPABASE_ENABLED:
        return None
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        _engine = create_engine(
            _DATABASE_URL,
            pool_size=3,
            max_overflow=2,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True,
        )
        logger.info("ARBS Supabase engine created: %s", _DATABASE_URL.split("@")[-1])
        return _engine


def get_raw_connection():
    """Return a raw psycopg2 connection for batch operations, or None."""
    engine = get_engine()
    if engine is None:
        return None
    return engine.raw_connection()
