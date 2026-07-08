from __future__ import annotations

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import LEG_COLUMNS, PACKAGE_COLUMNS
from SDRUtils._swappulse_scripts import _tape_schema_v2 as schema

_NEW_LEG = [
    "matched_ust_maturity", "special_tenor_type", "ust_cusip",
    "tape_label_ust_alias", "leg_tape_label_ust_alias",
    "matched_ust_maturity_trade_confidence",
]


def test_new_leg_columns_in_tuple():
    for c in _NEW_LEG:
        assert c in LEG_COLUMNS, c


def test_new_leg_columns_in_ddl():
    sql = schema.TAPE_SCHEMA_SQL_V2
    for c in _NEW_LEG:
        assert f"ADD COLUMN IF NOT EXISTS {c}" in sql, c


_NEW_PKG = ["special_tenor_type", "tape_label_ust_alias", "is_matched_maturity_all"]


def test_new_package_columns_in_tuple():
    for c in _NEW_PKG:
        assert c in PACKAGE_COLUMNS, c


def test_new_package_columns_in_ddl_and_view():
    sql = schema.TAPE_SCHEMA_SQL_V2
    for c in _NEW_PKG:
        assert f"ADD COLUMN IF NOT EXISTS {c}" in sql, c
    # package columns must be hand-listed in the display view SELECT
    for c in _NEW_PKG:
        assert f"p.{c}" in sql, c
