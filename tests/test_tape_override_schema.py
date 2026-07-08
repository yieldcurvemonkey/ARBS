"""DDL / schema tests for the manual-regrouping + notes tables (2026-07-08).

Mirrors the DB harness in test_ingest_usdswaps_tape_writepath.py: consumes the
``pg_test_url`` fixture, marks DB-dependent tests ``@pytest.mark.db``, and
asserts via engine.connect() + text().
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts import ingest_usdswaps_tape as _ing
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import (
    _schema_already_current,
    ensure_schema,
)
from SDRUtils._swappulse_scripts._tape_schema_v2 import (
    DISPLAY_VIEW_V2,
    LEGS_TABLE_V2,
    NOTES_TABLE_V2,
    OVERRIDE_HISTORY_TABLE_V2,
    OVERRIDE_MEMBERS_TABLE_V2,
    OVERRIDES_TABLE_V2,
    PACKAGES_TABLE_V2,
)


@pytest.fixture
def override_engine(pg_test_url):
    """Drop the four new objects, force ensure_schema to re-run, return engine."""
    engine = create_engine(pg_test_url)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_MEMBERS_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_HISTORY_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {NOTES_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDES_TABLE_V2} CASCADE"))
    _ing._schema_ensured.discard(str(engine.url))
    ensure_schema(engine)
    return engine


@pytest.mark.db
def test_override_tables_created(override_engine):
    expected = {
        OVERRIDES_TABLE_V2,
        OVERRIDE_MEMBERS_TABLE_V2,
        OVERRIDE_HISTORY_TABLE_V2,
        NOTES_TABLE_V2,
    }
    with override_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name = ANY(:names)"
            ),
            {"names": list(expected)},
        ).fetchall()
    found = {r[0] for r in rows}
    assert expected <= found, f"missing tables: {expected - found}"


@pytest.mark.db
def test_group_override_requires_two_trades(override_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDES_TABLE_V2} "
                    "(override_type, trade_ids, created_by) "
                    "VALUES ('GROUP', ARRAY['T1'], 'pytest')"
                )
            )
    with override_engine.begin() as conn:
        oid = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} "
                "(override_type, trade_ids, created_by) "
                "VALUES ('GROUP', ARRAY['T1','T2'], 'pytest') RETURNING override_id"
            )
        ).scalar()
    assert oid is not None


@pytest.mark.db
def test_override_type_check(override_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDES_TABLE_V2} "
                    "(override_type, trade_ids, created_by) "
                    "VALUES ('FOO', ARRAY['T1','T2'], 'pytest')"
                )
            )


@pytest.mark.db
def test_override_members_one_active_per_trade(override_engine):
    from sqlalchemy.exc import IntegrityError

    with override_engine.begin() as conn:
        oid1 = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} (override_type, trade_ids, created_by) "
                "VALUES ('GROUP', ARRAY['TX','TY'], 'pytest') RETURNING override_id"
            )
        ).scalar()
        oid2 = conn.execute(
            text(
                f"INSERT INTO {OVERRIDES_TABLE_V2} (override_type, trade_ids, created_by) "
                "VALUES ('GROUP', ARRAY['TX','TZ'], 'pytest') RETURNING override_id"
            )
        ).scalar()
        conn.execute(
            text(
                f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                "(trade_id, override_id, override_type, is_active) "
                "VALUES ('TX', :oid, 'GROUP', TRUE)"
            ),
            {"oid": oid1},
        )
    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                    "(trade_id, override_id, override_type, is_active) "
                    "VALUES ('TX', :oid, 'GROUP', TRUE)"
                ),
                {"oid": oid2},
            )
    # inactive duplicate is allowed (partial index is WHERE is_active)
    with override_engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {OVERRIDE_MEMBERS_TABLE_V2} "
                "(trade_id, override_id, override_type, is_active) "
                "VALUES ('TX', :oid, 'GROUP', FALSE)"
            ),
            {"oid": oid2},
        )


@pytest.mark.db
def test_notes_target_type_check(override_engine):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with override_engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {NOTES_TABLE_V2} "
                    "(target_type, target_id, author, body) "
                    "VALUES ('FOO', 'T1', 'pytest', 'hi')"
                )
            )


def test_latest_migration_cols_includes_overrides_table():
    from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import _LATEST_MIGRATION_COLS

    assert ("arbs_usd_swap_tape_overrides_v2", "override_id") in _LATEST_MIGRATION_COLS


@pytest.mark.db
def test_schema_not_current_when_overrides_missing(pg_test_url):
    engine = create_engine(pg_test_url)
    _ing._schema_ensured.discard(str(engine.url))
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_MEMBERS_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDE_HISTORY_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {NOTES_TABLE_V2} CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {OVERRIDES_TABLE_V2} CASCADE"))
    # Missing overrides table -> sentinel probe finds no row -> NOT current.
    assert _schema_already_current(engine) is False
    ensure_schema(engine)
    assert _schema_already_current(engine) is True
