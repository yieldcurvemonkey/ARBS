"""Schema migration tests for the USD swap tape v2 ingest.

Verifies that ``TAPE_SCHEMA_SQL`` creates all expected tables and the
display view, and that repeated execution is idempotent.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts._tape_schema import TAPE_SCHEMA_SQL


def _drop_all(conn) -> None:
    """Best-effort cleanup before each test."""
    for stmt in (
        "DROP VIEW IF EXISTS arbs_usd_swap_tape_display_v1",
        "DROP TABLE IF EXISTS arbs_usd_swap_tape_legs_v1 CASCADE",
        "DROP TABLE IF EXISTS arbs_usd_swap_tape_packages_v1 CASCADE",
        "DROP TABLE IF EXISTS arbs_usd_swap_tape_ingestion_runs_v1 CASCADE",
    ):
        conn.execute(text(stmt))


def _apply_schema(conn) -> None:
    """Execute the tape schema SQL statement-by-statement."""
    buffer: list[str] = []
    depth = 0
    for line in TAPE_SCHEMA_SQL.splitlines():
        stripped = line.strip()
        # Track $function$ dollar-quoted blocks if we ever add them.
        if stripped.startswith("DO $$"):
            depth += 1
        if stripped.endswith("$$;"):
            depth = max(0, depth - 1)
        buffer.append(line)
        if depth == 0 and stripped.endswith(";"):
            sql = "\n".join(buffer).strip()
            if sql:
                conn.execute(text(sql))
            buffer = []
    tail = "\n".join(buffer).strip()
    if tail:
        conn.execute(text(tail))


@pytest.fixture
def test_engine(pg_test_url):
    engine = create_engine(pg_test_url)
    with engine.connect() as conn:
        _drop_all(conn)
        conn.commit()
    return engine


def test_schema_creates_all_objects(test_engine):
    with test_engine.connect() as conn:
        _apply_schema(conn)
        conn.commit()
        result = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name LIKE 'arbs_usd_swap_tape_%'
            ORDER BY table_name
        """))
        tables = [r[0] for r in result]
    assert "arbs_usd_swap_tape_legs_v1" in tables
    assert "arbs_usd_swap_tape_packages_v1" in tables
    assert "arbs_usd_swap_tape_ingestion_runs_v1" in tables


def test_schema_is_idempotent(test_engine):
    with test_engine.connect() as conn:
        _apply_schema(conn)
        _apply_schema(conn)  # second run must not fail
        conn.commit()


def test_display_view_exists(test_engine):
    with test_engine.connect() as conn:
        _apply_schema(conn)
        conn.commit()
        result = conn.execute(text("""
            SELECT 1 FROM information_schema.views
            WHERE table_name = 'arbs_usd_swap_tape_display_v1'
        """))
        assert result.fetchone() is not None
