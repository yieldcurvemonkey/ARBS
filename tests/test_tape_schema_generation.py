from __future__ import annotations

import re

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts._tape_schema_current import (
    SIGNAL_TABLE_DDL,
    TAPE_SCHEMA_SQL_CURRENT,
)

# The VWAP DDL is inside TAPE_SCHEMA_SQL_CURRENT, not a separate constant.
ALL_DDL = TAPE_SCHEMA_SQL_CURRENT + SIGNAL_TABLE_DDL

# Index names are schema-global. An index name still pinned to v2 makes
# `CREATE INDEX IF NOT EXISTS` match the existing v2 index, skip, and
# report success -- leaving v3 unindexed on millions of rows.
INDEX_NAME_RE = re.compile(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS\s+(\w+)")


def test_no_index_name_is_pinned_to_v2():
    stray = sorted({n for n in INDEX_NAME_RE.findall(ALL_DDL) if "v2" in n})
    assert stray == [], f"index names still pinned to v2: {stray}"


def test_every_index_name_carries_the_generation():
    names = sorted(set(INDEX_NAME_RE.findall(ALL_DDL)))
    assert len(names) >= 36, f"expected >=36 index names, found {len(names)}"
    missing = [n for n in names if f"_{tt.IDX_INFIX}_" not in n]
    assert missing == [], f"index names missing the generation infix: {missing}"


def test_ddl_targets_v3_tables():
    assert tt.LEGS_TABLE in TAPE_SCHEMA_SQL_CURRENT
    assert tt.PACKAGES_TABLE in TAPE_SCHEMA_SQL_CURRENT
    assert tt.DISPLAY_VIEW in TAPE_SCHEMA_SQL_CURRENT
    assert "arbs_usd_swap_tape_legs_v2" not in ALL_DDL
    assert "arbs_usd_swap_tape_packages_v2" not in ALL_DDL


def test_vwap_block_is_parameterised():
    # The VWAP block sits inside TAPE_SCHEMA_SQL and hardcoded its table
    # name, with VWAP_TABLE_V2 defined *after* the DDL that should have
    # used it.
    assert tt.VWAP_TABLE in TAPE_SCHEMA_SQL_CURRENT
    assert "arbs_usd_swap_vwap_daily_v2" not in TAPE_SCHEMA_SQL_CURRENT


def test_manual_links_reference_is_still_v2():
    # The display view joins the shared, unversioned manual-links table.
    assert tt.MANUAL_LINKS_TABLE in TAPE_SCHEMA_SQL_CURRENT
